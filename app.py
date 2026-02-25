import os
import asyncio
import json
import logging
import cv2
import aiomysql
import aiosqlite
import bcrypt
import aiohttp_jinja2
import jinja2
import uuid
import re # Importado para validação de senha
from aiohttp import web, WSMsgType

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ROOT = os.path.dirname(__file__)
VERSION = os.environ.get('APP_VERSION', 'dev-local')
DB_TYPE = os.environ.get('DB_TYPE', 'sqlite').lower()

connected_clients = set()
camera_task = None
cap = None
db_pool = None 
active_sessions = {}

# --- FUNÇÃO DE VALIDAÇÃO DE SENHA FORTE ---
def is_strong_password(password):
    if len(password) < 8: return False
    if not re.search(r'[A-Z]', password): return False # Pelo menos uma maiúscula
    if not re.search(r'[a-z]', password): return False # Pelo menos uma minúscula
    if not re.search(r'\d', password): return False    # Pelo menos um número
    if not re.search(r'[!@#$%^&*(),.?":{}|<>\-=_+\[\]\\/`~]', password): return False # Pelo menos um símbolo
    return True

# --- BANCO DE DADOS: INICIALIZAÇÃO E MIGRAÇÃO ---
async def init_db(app):
    global db_pool
    if DB_TYPE == 'mysql':
        for i in range(20):
            try:
                db_pool = await aiomysql.create_pool(
                    host=os.environ.get('DB_HOST', 'db'), port=3306,
                    user=os.environ.get('DB_USER', 'stream_user'), password=os.environ.get('DB_PASS', 'stream_pass'),
                    db=os.environ.get('DB_NAME', 'stream_db'), autocommit=True
                )
                logger.info("Conectado ao MySQL com sucesso!")
                break
            except Exception as e:
                logger.warning(f"Aguardando o MySQL (Tentativa {i+1}/20)...")
                await asyncio.sleep(5)
                
        if not db_pool: return
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NOT NULL
                    )
                """)
                try: await cur.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
                except: pass

                # Verifica se o banco está VAZIO antes de criar o admin padrão
                await cur.execute("SELECT COUNT(*) FROM users")
                result = await cur.fetchone()
                count = result[0] if result else 0
                
                if count == 0:
                    hashed = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode('utf-8')
                    await cur.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, TRUE)", ('admin', hashed))
                    logger.info("Banco vazio: Usuário 'admin' padrão criado.")
                    
    elif DB_TYPE == 'sqlite':
        db_path = os.environ.get('DB_NAME', os.path.join(ROOT, 'data/stream.db'))
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db_pool = await aiosqlite.connect(db_path)
        db_pool.row_factory = aiosqlite.Row
        
        await db_pool.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL
            )
        """)
        try: await db_pool.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
        except: pass
        await db_pool.commit()
        
        # Verifica se o banco está VAZIO antes de criar o admin padrão
        async with db_pool.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            if row and row[0] == 0:
                hashed = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode('utf-8')
                await db_pool.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)", ('admin', hashed))
                await db_pool.commit()
                logger.info("Banco vazio: Usuário 'admin' padrão criado.")

# --- CONSULTAS DE USUÁRIOS ---
async def get_user_data(username):
    if DB_TYPE == 'mysql':
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT password_hash, is_admin FROM users WHERE username=%s", (username,))
                return await cur.fetchone()
    else:
        async with db_pool.execute("SELECT password_hash, is_admin FROM users WHERE username=?", (username,)) as cursor:
            return await cursor.fetchone()

async def get_all_users():
    if DB_TYPE == 'mysql':
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT id, username, is_admin FROM users ORDER BY username ASC")
                return await cur.fetchall()
    else:
        async with db_pool.execute("SELECT id, username, is_admin FROM users ORDER BY username ASC") as cursor:
            return [dict(row) for row in await cursor.fetchall()]

# --- MIDDLEWARE DE AUTENTICAÇÃO ---
@web.middleware
async def auth_middleware(request, handler):
    if request.path in ['/login', '/static']: return await handler(request)
    token = request.cookies.get('stream_token')
    if not token or token not in active_sessions:
        if request.path == '/ws': return web.Response(status=401)
        raise web.HTTPFound('/login')
    request['user'] = active_sessions[token]
    return await handler(request)

# --- ROTAS BÁSICAS (Login, Logout, Stream) ---
@aiohttp_jinja2.template('login.html')
async def login_get(request): return {'version': VERSION, 'error': None}

@aiohttp_jinja2.template('login.html')
async def login_post(request):
    data = await request.post()
    username, password = data.get('username'), data.get('password')
    if not db_pool: return {'version': VERSION, 'error': 'Banco offline.'}
    try:
        user = await get_user_data(username)
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            token = str(uuid.uuid4())
            active_sessions[token] = {'username': username, 'is_admin': bool(user['is_admin'])}
            response = web.HTTPFound('/')
            response.set_cookie('stream_token', token, max_age=86400)
            return response
        return {'version': VERSION, 'error': 'Usuário ou senha incorretos!'}
    except Exception as e:
        logger.error(f"Erro: {e}")
        return {'version': VERSION, 'error': 'Erro interno.'}

async def logout(request):
    token = request.cookies.get('stream_token')
    if token in active_sessions: del active_sessions[token]
    response = web.HTTPFound('/login')
    response.del_cookie('stream_token')
    return response

@aiohttp_jinja2.template('index.html')
async def index(request): return {'version': VERSION, 'is_admin': request['user']['is_admin']}

# --- DASHBOARD DE GESTÃO DE USUÁRIOS ---
@aiohttp_jinja2.template('users.html')
async def users_get(request):
    user = request['user']
    if not user['is_admin']: raise web.HTTPFound('/')
    users_list = await get_all_users()
    return {'version': VERSION, 'is_admin': True, 'msg': None, 'error': None, 'users': users_list, 'current_user': user['username']}

@aiohttp_jinja2.template('users.html')
async def users_post(request):
    user = request['user']
    if not user['is_admin']: raise web.HTTPFound('/')
    
    data = await request.post()
    action = data.get('action')
    ctx = {'version': VERSION, 'is_admin': True, 'current_user': user['username']}
    
    try:
        if action == 'add':
            new_user = data.get('username')
            pwd = data.get('password')
            
            if pwd != data.get('confirm_password'):
                ctx['error'] = 'As senhas não conferem!'
            elif not is_strong_password(pwd):
                ctx['error'] = 'A senha deve ter no mínimo 8 caracteres, com pelo menos uma letra maiúscula, uma minúscula, um número e um símbolo especial.'
            else:
                is_admin = 1 if data.get('is_admin') == 'on' else 0
                hashed = bcrypt.hashpw(pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                if DB_TYPE == 'mysql':
                    async with db_pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, %s)", (new_user, hashed, is_admin))
                else:
                    await db_pool.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)", (new_user, hashed, is_admin))
                    await db_pool.commit()
                ctx['msg'] = f'Usuário {new_user} criado com sucesso!'

        elif action == 'edit':
            target_user = data.get('username')
            pwd = data.get('password')
            
            # --- PROTEÇÃO CONTRA AUTO-REVOGAÇÃO ---
            if target_user == user['username']:
                is_admin = 1 # Garante que o usuário logado nunca perca o próprio admin
            else:
                is_admin = 1 if data.get('is_admin') == 'on' else 0
            
            if pwd: # Se digitou algo na senha, altera a senha e o privilégio
                if pwd != data.get('confirm_password'):
                    ctx['error'] = 'As novas senhas não conferem!'
                elif not is_strong_password(pwd):
                    ctx['error'] = 'A nova senha deve ter no mínimo 8 caracteres, com pelo menos uma letra maiúscula, uma minúscula, um número e um símbolo especial.'
                else:
                    hashed = bcrypt.hashpw(pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    if DB_TYPE == 'mysql':
                        async with db_pool.acquire() as conn:
                            async with conn.cursor() as cur:
                                await cur.execute("UPDATE users SET password_hash=%s, is_admin=%s WHERE username=%s", (hashed, is_admin, target_user))
                    else:
                        await db_pool.execute("UPDATE users SET password_hash=?, is_admin=? WHERE username=?", (hashed, is_admin, target_user))
                        await db_pool.commit()
                    ctx['msg'] = f'Senha e privilégios de {target_user} atualizados!'
            else: # Se deixou a senha em branco, altera apenas o privilégio
                if DB_TYPE == 'mysql':
                    async with db_pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("UPDATE users SET is_admin=%s WHERE username=%s", (is_admin, target_user))
                else:
                    await db_pool.execute("UPDATE users SET is_admin=? WHERE username=?", (is_admin, target_user))
                    await db_pool.commit()
                ctx['msg'] = f'Privilégios de {target_user} atualizados!'
                
                # Se o admin tirou o próprio privilégio, desloga ele na próxima
                if target_user == user['username'] and not is_admin:
                    active_sessions[request.cookies.get('stream_token')]['is_admin'] = False

        elif action == 'delete':
            target_user = data.get('username')
            if target_user == user['username']:
                ctx['error'] = 'Falha de segurança: Você não pode excluir a si mesmo!'
            else:
                if DB_TYPE == 'mysql':
                    async with db_pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("DELETE FROM users WHERE username=%s", (target_user,))
                else:
                    await db_pool.execute("DELETE FROM users WHERE username=?", (target_user,))
                    await db_pool.commit()
                ctx['msg'] = f'Usuário {target_user} removido permanentemente do sistema.'

    except Exception as e:
        ctx['error'] = f'Falha na operação. Verifique se o nome de usuário já existe.'

    ctx['users'] = await get_all_users()
    return ctx

# --- WEBSOCKET E CÂMERA (Inalterados) ---
async def notify_viewers():
    count = len(connected_clients)
    message = json.dumps({"type": "viewers", "count": count})
    for ws in list(connected_clients):
        try: await ws.send_str(message)
        except: pass

async def broadcast_camera():
    global cap, connected_clients
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    try:
        while connected_clients:
            ret, frame = cap.read()
            if not ret:
                await asyncio.sleep(0.1)
                continue
            ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ret:
                data = buffer.tobytes()
                current_clients = list(connected_clients)
                if current_clients:
                    tasks = [ws.send_bytes(data) for ws in current_clients]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    disconnected = False
                    for ws, res in zip(current_clients, results):
                        if isinstance(res, Exception):
                            connected_clients.discard(ws)
                            disconnected = True
                    if disconnected: await notify_viewers()
            await asyncio.sleep(0.033)
    finally:
        cap.release()
        cap = None

async def websocket_handler(request):
    global camera_task, connected_clients
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connected_clients.add(ws)
    await notify_viewers()
    if len(connected_clients) == 1: camera_task = asyncio.create_task(broadcast_camera())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT and msg.data == 'stop': await ws.close()
    finally:
        connected_clients.discard(ws)
        await notify_viewers()
        if len(connected_clients) == 0 and camera_task: await camera_task
    return ws

app = web.Application(middlewares=[auth_middleware])
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(os.path.join(ROOT, 'templates')))
app.on_startup.append(init_db)
app.router.add_get("/", index)
app.router.add_get("/login", login_get)
app.router.add_post("/login", login_post)
app.router.add_get("/logout", logout)
app.router.add_get("/users", users_get)
app.router.add_post("/users", users_post)
app.router.add_get("/ws", websocket_handler)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8080, access_log=logger)