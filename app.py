import os
import json
import logging
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

# Configuração de logs detalhados
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ROOT = os.path.dirname(__file__)

async def index(request):
    logger.info("Novo acesso à interface web.")
    content = open(os.path.join(ROOT, "index.html"), "r", encoding="utf-8").read()
    return web.Response(content_type="text/html", text=content)

async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    
    logger.info("Recebida requisição WebRTC. Negociando conexão...")

    pc = RTCPeerConnection()
    
    # Monitora o status da conexão em tempo real
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"Status da conexão WebRTC: {pc.connectionState}")
        if pc.connectionState == "failed" or pc.connectionState == "closed":
            logger.warning("Conexão WebRTC encerrada pelo cliente.")
            await pc.close()

    # Captura a webcam
    player = MediaPlayer('/dev/video0', format='v4l2', options={'video_size': '640x480'})
    
    if player and player.video:
        pc.addTrack(player.video)
        logger.info("Faixa de vídeo (/dev/video0) injetada no stream com sucesso.")
    else:
        logger.error("Falha ao ler o dispositivo de vídeo.")

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    logger.info("Sinalização concluída. Stream iniciando...")

    return web.Response(
        content_type="application/json",
        text=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
    )

if __name__ == "__main__":
    logger.info("Iniciando o Servidor de Stream de Henrique Fagundes na porta 8080...")
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/offer", offer)
    # Habilitamos o access_log do aiohttp para ver as rotas acessadas
    web.run_app(app, host="0.0.0.0", port=8080, access_log=logger)