import os
import json
import logging
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer, MediaRelay

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ROOT = os.path.dirname(__file__)

# Gerenciadores globais para o Hardware
global_player = None
relay = None
active_pcs = set()

async def index(request):
    content = open(os.path.join(ROOT, "index.html"), "r", encoding="utf-8").read()
    return web.Response(content_type="text/html", text=content)

async def offer(request):
    global global_player, relay
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    active_pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        global global_player
        logger.info(f"Status da conexão WebRTC: {pc.connectionState}")
        
        # Se o cliente clicou em desligar ou fechou a página
        if pc.connectionState in ["failed", "closed", "disconnected"]:
            active_pcs.discard(pc)
            # Se não sobrar ninguém conectado, desliga a câmera física (apaga o LED)
            if len(active_pcs) == 0 and global_player is not None:
                logger.info("Nenhum cliente assistindo. Desligando o hardware de vídeo...")
                global_player.video.stop()
                global_player = None

    # Liga a câmera apenas se ela já não estiver ligada
    if global_player is None:
        logger.info("Iniciando leitura física em /dev/video0...")
        global_player = MediaPlayer('/dev/video0', format='v4l2', options={'video_size': '640x480'})
        relay = MediaRelay()
    
    # Usa o Relay para distribuir a mesma imagem para vários acessos remotos
    if global_player and global_player.video:
        video_track = relay.subscribe(global_player.video)
        pc.addTrack(video_track)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
    )

if __name__ == "__main__":
    logger.info("Sistema Iniciado na porta 8080...")
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/offer", offer)
    web.run_app(app, host="0.0.0.0", port=8080, access_log=logger)