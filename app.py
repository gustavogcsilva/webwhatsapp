from flask import Flask, request, jsonify
import mysql.connector
import os
import requests

app = Flask(__name__)


banco_dados = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'port': int(os.getenv('DB_PORT', 12345)),
    'database': os.getenv('DB_NAME')
}

fluxo_usuarios = {}

if not os.path.exists('uploads'):
    os.makedirs('uploads')

@app.route("/webhook", methods=['POST'])
def webhook():
    try:
        dados = request.get_json()
        if not dados:
            return jsonify({"status": "erro", "message": "Sem dados JSON"}), 400

        # Captura segura de dados (Ajustado para o padrão comum de instâncias)
        usuario = dados.get('data', {}).get('key', {}).get('remoteJid')
        if not usuario:
            return jsonify({"status": "ignorado"}), 200 # Ignora notificações que não são mensagens

        # Pega o texto da mensagem de diferentes campos possíveis
        mensagem = (dados.get('data', {}).get('message', {}).get('conversation') or 
                    dados.get('data', {}).get('message', {}).get('extendedTextMessage', {}).get('text') or 
                    "").strip().lower()

        # Captura URL de mídia (Imagem ou Documento)
        msg_content = dados.get('data', {}).get('message', {})
        midia_url = None
        if 'imageMessage' in msg_content:
            midia_url = msg_content['imageMessage'].get('url')
        elif 'documentMessage' in msg_content:
            midia_url = msg_content['documentMessage'].get('url')

        print(f"[GCS LOG] Mensagem de: {usuario} | Texto: {mensagem} | Mídia: {'Sim' if midia_url else 'Não'}")

        # LÓGICA DE FLUXO
        if usuario not in fluxo_usuarios:
            fluxo_usuarios[usuario] = {'passo': 'menu'}
            return "Olá! Sou seu assistente do GCS. Qual comprovante deseja cadastrar?\n1. Luz\n2. Água\n3. Cartão\n4. Internet\n5. Outros"

        estado = fluxo_usuarios[usuario]

        if estado['passo'] == 'menu':
            categorias = {"1": "Luz", "2": "Água", "3": "Cartão", "4": "Internet", "5": "Outros"}
            if mensagem in categorias:
                estado['categoria'] = categorias[mensagem]
                estado['passo'] = 'aguardando_arquivo'
                return f"Muito bom! Agora anexe o PDF ou imagem de {estado['categoria']}."
            return "Opção inválida. Escolha de 1 a 5."

        if estado['passo'] == 'aguardando_arquivo':
            if midia_url:
                ext = ".pdf" if "pdf" in midia_url or 'document' in str(msg_content) else ".jpg"
                nome_arquivo = f"uploads/{usuario.replace('@', '_')}_{estado['categoria']}{ext}"
                
                # Download real do arquivo
                try:
                    res = requests.get(midia_url, timeout=10)
                    with open(nome_arquivo, 'wb') as f:
                        f.write(res.content)
                    estado['arquivo'] = nome_arquivo
                    estado['passo'] = 'aguardando_mes'
                    return "Arquivo recebido! Agora digite o mês e título (Ex: Março - Aluguel)."
                except:
                    return "Erro ao baixar arquivo. Tente enviar novamente."
            return "Por favor, anexe um arquivo."

        if estado['passo'] == 'aguardando_mes':
            conn = mysql.connector.connect(**banco_dados)
            cursor = conn.cursor()
            sql = "INSERT INTO comprovantes (usuario_whatsapp, categoria, mes_referencia, caminho_arquivo) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (usuario, estado['categoria'], mensagem, estado['arquivo']))
            conn.commit()
            cursor.close()
            conn.close()
            del fluxo_usuarios[usuario]
            return f"✔️ Comprovante de {mensagem} cadastrado com sucesso!"

    except Exception as e:
        print(f"ERRO NO WEBHOOK: {e}")
        return "Ops, tive um problema interno. Tente novamente em instantes."

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(port=5000, debug=True)