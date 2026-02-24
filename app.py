import os
import asyncio
import json
import logging
import cv2
from aiohttp import web, WSMsgType

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ROOT = os.path.dirname(__file__)

connected_clients = set()
camera_task = None
cap = None

async def index(request):
    content = open(os.path.join(ROOT, "index.html"), "r", encoding="utf-8").read()
    return web.Response(content_type="text/html", text=content)

async def notify_viewers():
    count = len(connected_clients)
    message = json.dumps({"type": "viewers", "count": count})
    # Usa list() para criar uma cópia estática e evitar erro de concorrência
    for ws in list(connected_clients):
        try:
            await ws.send_str(message)
        except Exception:
            pass

async def broadcast_camera():
    global cap, connected_clients
    logger.info("Iniciando captura física em /dev/video0...")
    
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        logger.error("Falha ao acessar o hardware de vídeo.")
        return

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
                
                # 1. Congela a lista de clientes atual para este frame
                current_clients = list(connected_clients)
                
                if current_clients:
                    # 2. Cria as tarefas de envio para todos simultaneamente
                    tasks = [ws.send_bytes(data) for ws in current_clients]
                    
                    # 3. Executa todas as tarefas em paralelo sem travar o loop
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # 4. Verifica se alguém fechou o navegador durante o envio
                    disconnected = False
                    for ws, result in zip(current_clients, results):
                        if isinstance(result, Exception):
                            connected_clients.discard(ws)
                            disconnected = True
                    
                    if disconnected:
                        await notify_viewers()

            # Mantém ~30 fps
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
    logger.info(f"Novo acesso. Espectadores: {len(connected_clients)}")
    await notify_viewers()

    if len(connected_clients) == 1:
        camera_task = asyncio.create_task(broadcast_camera())

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT and msg.data == 'stop':
                await ws.close()
            elif msg.type == WSMsgType.ERROR:
                logger.error('Conexão WebSocket fechada com erro.')
    finally:
        connected_clients.discard(ws)
        logger.info(f"Acesso encerrado. Espectadores: {len(connected_clients)}")
        
        await notify_viewers()
        
        if len(connected_clients) == 0 and camera_task:
            await camera_task

    return ws

app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/ws", websocket_handler)

if __name__ == "__main__":
    logger.info("Sistema de Stream Iniciado na porta 8080...")
    web.run_app(app, host="0.0.0.0", port=8080, access_log=logger)