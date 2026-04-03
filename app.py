from flask import Flask, request, abort
import mysql.connector
from mysql.connector import pooling
import os
from datetime import datetime
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from functools import wraps

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
TWILIO_TOKEN = os.getenv('TWILIO_TOKEN')
BOT_URL = os.getenv('BOT_URL')
validator = RequestValidator(TWILIO_TOKEN)

# Pool de conexões MySQL com verificação de erro
try:
    db_pool = mysql.connector.pooling.MySQLConnectionPool(
        pool_name="gcs_pool",
        pool_size=5,
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306))
    )
except Exception as e:
    print(f"❌ Erro ao iniciar Pool do MySQL: {e}")

fluxo_usuarios = {}

def validar_twilio(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        signature = request.headers.get('X-Twilio-Signature', '')
        # Importante: O Render às vezes muda o protocolo para HTTP, o validador pode falhar.
        # Se falhar muito, verifique se o BOT_URL começa com https://
        if not validator.validate(BOT_URL, request.form, signature):
            print("[GCS SEGURANÇA] Bloqueado: Assinatura Inválida.")
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@app.route("/webhook", methods=['POST'])
#@validar_twilio
def webhook():
    usuario = request.values.get('From')
    mensagem = request.values.get('Body', '').strip().lower()
    num_midia = int(request.values.get('NumMedia', 0))
    resp = MessagingResponse()

    # --- COMANDOS GLOBAIS (Sempre funcionam) ---
    if mensagem in ["cancelar", "sair", "menu", "reset"]:
        if usuario in fluxo_usuarios:
            del fluxo_usuarios[usuario]
        resp.message("Operação cancelada. Digite *oi* para ver o menu principal.")
        return str(resp)

    if mensagem == "ver":
        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            query = "SELECT categoria, data_cadastro, link_comprovante FROM comprovantes WHERE usuario_whatsapp = %s ORDER BY data_cadastro DESC LIMIT 3"
            cursor.execute(query, (usuario,))
            rows = cursor.fetchall()
            if rows:
                txt = "📂 *Seus últimos comprovantes:*\n"
                for row in rows:
                    txt += f"\n📌 {row[0]} ({row[1].strftime('%d/%m/%Y')})\n🔗 {row[2]}\n"
                resp.message(txt)
            else:
                resp.message("Você ainda não tem comprovantes salvos.")
        except Exception as e:
            print(f"Erro ao buscar: {e}")
            resp.message("⚠️ Erro ao acessar o banco de dados.")
        finally:
            if conn: conn.close()
        return str(resp)

    # --- LÓGICA DE FLUXO ---
    if usuario not in fluxo_usuarios:
        fluxo_usuarios[usuario] = {'passo': 'menu'}
        msg = ("Olá! Sou o assistente GCS.\n\n"
               "Qual comprovante deseja cadastrar?\n"
               "1. Luz\n2. Água\n3. Cartão\n4. Internet\n5. Outros\n\n"
               "💡 Digite *ver* para listar ou *cancelar* para parar.")
        resp.message(msg)
        return str(resp)

    estado = fluxo_usuarios[usuario]

    if estado['passo'] == 'menu':
        categorias = {"1": "Luz", "2": "Água", "3": "Cartão", "4": "Internet", "5": "Outros"}
        if mensagem in categorias:
            estado['categoria'] = categorias[mensagem]
            estado['passo'] = 'aguardando_arquivo'
            resp.message(f"Boa! Agora envie o arquivo de *{estado['categoria']}*.\n\n_(Ou digite cancelar)_")
        else:
            resp.message("Por favor, escolha uma opção de 1 a 5 ou digite *ver*.")
        return str(resp)

    if estado['passo'] == 'aguardando_arquivo':
        if num_midia > 0:
            link_arquivo = request.values.get('MediaUrl0')
            conn = None
            try:
                conn = db_pool.get_connection()
                cursor = conn.cursor()
                sql = "INSERT INTO comprovantes (usuario_whatsapp, categoria, data_cadastro, link_comprovante) VALUES (%s, %s, %s, %s)"
                cursor.execute(sql, (usuario, estado['categoria'], datetime.now(), link_arquivo))
                conn.commit()
                del fluxo_usuarios[usuario] # Limpa memória após sucesso
                resp.message(f"✔️ Comprovante de *{estado['categoria']}* salvo com sucesso no Aiven!")
            except Exception as e:
                print(f"Erro ao salvar: {e}")
                resp.message("⚠️ Erro ao salvar arquivo. Tente novamente.")
            finally:
                if conn: conn.close()
        else:
            resp.message("Ainda estou aguardando o arquivo. Envie a foto/PDF ou digite *cancelar*.")
        return str(resp)

    return str(resp)

@app.route("/healthcheck")
def health():
    return "Bot GCS Online", 200

if __name__ == "__main__":
    # Render usa a porta 10000 por padrão, mas injeta via variável
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)