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

async def init_db(app):
    global db_pool
    
    if DB_TYPE == 'mysql':
        for i in range(20):
            try:
                db_pool = await aiomysql.create_pool(
                    host=os.environ.get('DB_HOST', 'db'),
                    port=3306,
                    user=os.environ.get('DB_USER', 'stream_user'),
                    password=os.environ.get('DB_PASS', 'stream_pass'),
                    db=os.environ.get('DB_NAME', 'stream_db'),
                    autocommit=True
                )
                logger.info("Conectado ao MySQL com sucesso!")
                break
            except Exception as e:
                logger.warning(f"Aguardando o MySQL inicializar (Tentativa {i+1}/20)...")
                await asyncio.sleep(5)
                
        if not db_pool:
            logger.error("Falha crítica: Tempo esgotado ao tentar conectar no MySQL.")
            return

        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NOT NULL
                    )
                """)
                await cur.execute("SELECT * FROM users WHERE username='admin'")
                if not await cur.fetchone():
                    hashed = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode('utf-8')
                    await cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", ('admin', hashed))
                    logger.info("Usuário padrão MySQL criado: admin / admin123")
                    
    elif DB_TYPE == 'sqlite':
        db_path = os.environ.get('DB_NAME', os.path.join(ROOT, 'data/stream.db'))
        # Garante que a pasta 'data' existe para o volume
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        db_pool = await aiosqlite.connect(db_path)
        db_pool.row_factory = aiosqlite.Row
        logger.info(f"Conectado ao SQLite com sucesso em {db_path}!")
        
        await db_pool.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        await db_pool.commit()
        
        async with db_pool.execute("SELECT * FROM users WHERE username='admin'") as cursor:
            user = await cursor.fetchone()
            if not user:
                hashed = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode('utf-8')
                await db_pool.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ('admin', hashed))
                await db_pool.commit()
                logger.info("Usuário padrão SQLite criado: admin / admin123")

# --- BANCO DE DADOS: CONSULTA UNIVERSAL ---
async def get_user_hash(username):
    if DB_TYPE == 'mysql':
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT password_hash FROM users WHERE username=%s", (username,))
                row = await cur.fetchone()
                return row['password_hash'] if row else None
    else: # sqlite
        async with db_pool.execute("SELECT password_hash FROM users WHERE username=?", (username,)) as cursor:
            row = await cursor.fetchone()
            return row['password_hash'] if row else None

# --- MIDDLEWARE E ROTAS ---
@web.middleware
async def auth_middleware(request, handler):
    if request.path in ['/login', '/static']:
        return await handler(request)
    auth_cookie = request.cookies.get('stream_auth')
    if not auth_cookie or auth_cookie != 'authenticated_session':
        if request.path == '/ws': return web.Response(status=401)
        raise web.HTTPFound('/login')
    return await handler(request)

@aiohttp_jinja2.template('login.html')
async def login_get(request):
    return {'version': VERSION, 'error': None}

@aiohttp_jinja2.template('login.html')
async def login_post(request):
    data = await request.post()
    username = data.get('username')
    password = data.get('password')

    if not db_pool:
        return {'version': VERSION, 'error': 'Banco de dados offline. Tente novamente.'}

    try:
        user_hash = await get_user_hash(username)
        if user_hash and bcrypt.checkpw(password.encode('utf-8'), user_hash.encode('utf-8')):
            response = web.HTTPFound('/')
            response.set_cookie('stream_auth', 'authenticated_session', max_age=86400)
            return response
        return {'version': VERSION, 'error': 'Usuário ou senha incorretos!'}
    except Exception as e:
        logger.error(f"Erro durante o login: {e}")
        return {'version': VERSION, 'error': 'Erro interno ao consultar credenciais.'}

async def logout(request):
    response = web.HTTPFound('/login')
    response.del_cookie('stream_auth')
    return response

@aiohttp_jinja2.template('index.html')
async def index(request):
    return {'version': VERSION}

async def notify_viewers():
    count = len(connected_clients)
    message = json.dumps({"type": "viewers", "count": count})
    for ws in list(connected_clients):
        try: await ws.send_str(message)
        except Exception: pass

async def broadcast_camera():
    global cap, connected_clients
    logger.info("Iniciando captura física em /dev/video0...")
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    try:
        while connected_clients:
            ret, frame = cap.read()
            if not ret:
                await asyncio.sleep(0.1)
                continue
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 70]
            ret, buffer = cv2.imencode('.jpg', frame, encode_param)
            if ret:
                data = buffer.tobytes()
                current_clients = list(connected_clients)
                if current_clients:
                    tasks = [ws.send_bytes(data) for ws in current_clients]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    disconnected = False
                    for ws, result in zip(current_clients, results):
                        if isinstance(result, Exception):
                            connected_clients.discard(ws)
                            disconnected = True
                    if disconnected:
                        await notify_viewers()
            await asyncio.sleep(0.033)
    finally:
        logger.info("Encerrando transmissão e liberando o hardware.")
        cap.release()
        cap = None

async def websocket_handler(request):
    global camera_task, connected_clients
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connected_clients.add(ws)
    await notify_viewers()

    if len(connected_clients) == 1:
        camera_task = asyncio.create_task(broadcast_camera())

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT and msg.data == 'stop':
                await ws.close()
    finally:
        connected_clients.discard(ws)
        await notify_viewers()
        if len(connected_clients) == 0 and camera_task:
            await camera_task
    return ws

app = web.Application(middlewares=[auth_middleware])
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(os.path.join(ROOT, 'templates')))

app.on_startup.append(init_db)

app.router.add_get("/", index)
app.router.add_get("/login", login_get)
app.router.add_post("/login", login_post)
app.router.add_get("/logout", logout)
app.router.add_get("/ws", websocket_handler)

if __name__ == "__main__":
    logger.info(f"Sistema Iniciado na porta 8080. Motor de banco de dados: {DB_TYPE.upper()}")
    web.run_app(app, host="0.0.0.0", port=8080, access_log=logger)