from flask import Flask, request, jsonify
import mysql.connector
import os
import requests

app = Flask(__name__)

# Configuração do banco via Variáveis de Ambiente (Render)
banco_dados = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'port': int(os.getenv('DB_PORT', 12345)),
    'database': os.getenv('DB_NAME')
}

fluxo_usuarios = {}

# IMPORTANTE: Substitua SUA_INSTANCIA e SEU_TOKEN pelos dados do painel Z-API
ZAPI_ID = os.getenv("3FC228xak1iza1NsmsuCBtaKXLRXyW82XZ")
ZAPI_TOKEN = os.getenv("D385F5D82C7E5C64863E1AD8")
ZAPI_URL = f"https://api.z-api.io/instances/{ZAPI_ID}/token/{ZAPI_TOKEN}/send-text"

def enviar_mensagem(numero, texto):
    payload = {"phone": numero, "message": texto}
    try:
        requests.post(ZAPI_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")

if not os.path.exists('uploads'):
    os.makedirs('uploads')

@app.route("/webhook", methods=['POST'])
def webhook():
    try:
        dados = request.get_json()
        if not dados:
            return "No JSON", 400

        # Padrão Z-API para capturar número e texto
        usuario = dados.get('phone')
        mensagem = (dados.get('text', {}).get('message') or "").strip().lower()

        # Captura de Mídia (Z-API envia a URL pronta se habilitado)
        midia_url = dados.get('valueUrl') or dados.get('image', {}).get('url') or dados.get('document', {}).get('url')

        print(f"[GCS LOG] Zap: {usuario} | Msg: {mensagem} | Tem Mídia: {'Sim' if midia_url else 'Não'}")

        # --- LÓGICA DE FLUXO (A MÁQUINA DE ESTADOS) ---
        
        # 1. Início da conversa
        if usuario not in fluxo_usuarios:
            fluxo_usuarios[usuario] = {'passo': 'menu'}
            msg = "Olá! Sou o assistente GCS.\nQual comprovante deseja cadastrar?\n\n1. Luz\n2. Água\n3. Cartão\n4. Internet\n5. Outros"
            enviar_mensagem(usuario, msg)
            return "OK", 200

        estado = fluxo_usuarios[usuario]

        # 2. Escolha da Categoria
        if estado['passo'] == 'menu':
            categorias = {"1": "Luz", "2": "Água", "3": "Cartão", "4": "Internet", "5": "Outros"}
            if mensagem in categorias:
                estado['categoria'] = categorias[mensagem]
                estado['passo'] = 'aguardando_arquivo'
                enviar_mensagem(usuario, f"Boa! Agora anexe o PDF ou foto de {estado['categoria']}.")
            else:
                enviar_mensagem(usuario, "Opção inválida. Digite de 1 a 5.")
            return "OK", 200

        # 3. Recebimento do Arquivo
        if estado['passo'] == 'aguardando_arquivo':
            if midia_url:
                ext = ".pdf" if "pdf" in midia_url or dados.get('type') == 'Document' else ".jpg"
                nome_arquivo = f"uploads/{usuario}_{estado['categoria']}{ext}".replace(':', '_')
                
                # Download
                res = requests.get(midia_url, timeout=15)
                with open(nome_arquivo, 'wb') as f:
                    f.write(res.content)
                
                estado['arquivo'] = nome_arquivo
                estado['passo'] = 'aguardando_mes'
                enviar_mensagem(usuario, "Recebi! Agora digite o Mês e o Título (Ex: Março - Aluguel).")
            else:
                enviar_mensagem(usuario, "Por favor, anexe o arquivo (PDF ou Imagem).")
            return "OK", 200

        # 4. Finalização e SQL
        if estado['passo'] == 'aguardando_mes':
            conn = mysql.connector.connect(**banco_dados)
            cursor = conn.cursor()
            sql = "INSERT INTO comprovantes (usuario_whatsapp, categoria, mes_referencia, caminho_arquivo) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (usuario, estado['categoria'], mensagem, estado['arquivo']))
            conn.commit()
            cursor.close()
            conn.close()
            
            del fluxo_usuarios[usuario]
            enviar_mensagem(usuario, f"✔️ Comprovante de {mensagem} cadastrado com sucesso!")
            return "OK", 200

    except Exception as e:
        print(f"ERRO CRÍTICO: {e}")
        return "Erro Interno", 500

    return "OK", 200

if __name__ == "__main__":
    # Importante para o Render capturar a porta correta
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)