== Ativar ambiente virtual ==
cd ~/lavpop-bot
source venv/bin/activate

== Subir API ==
uvicorn main:app --host 0.0.0.0 --port 8000
ou
python -m uvicorn main:app --host 0.0.0.0 --port 8000

== Subir túnel (Cloudflare) ==
cloudflared tunnel --url http://localhost:8000

vai gerar url
https://xxxxx.trycloudflare.com

No Twilio / WhatsApp:
https://xxxxx.trycloudflare.com/webhook
