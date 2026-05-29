from flask import Flask, request, session
from flask_socketio import SocketIO, emit
from google import genai
from google.genai import types
from dotenv import load_dotenv
from uuid import uuid4
import os

load_dotenv()

instrucoes = """
Você é um assistente virtual amigável e prestativo. Sua função é responder a perguntas dos usuários e fornecer informações úteis somente sobre a Sociedade Esportiva Palmeiras. Nunca responda sobre outros clubes. Caso o receba essa pergunta, fale que você não conhece times de pequena expressão.
Tente manter as respostas curtas, concisas, objetivas e claras. Se não souber a resposta, diga que não sabe e sugira que o usuário procure em outro lugar.
"""

client = genai.Client(api_key=os.getenv("GENAI_KEY"))

app = Flask(__name__)

app.secret_key = "uma_chave_secreta_muito_forte_padrao"

# Configuração do CORS para Flask-SocketIO
# Permitir todas as origens para desenvolvimento. Em produção, restrinja para o seu domínio de frontend.
# Exemplo: 
# socketio = SocketIO(app, cors_allowed_origins=["https://seu-dominio.com"])
socketio = SocketIO(app, cors_allowed_origins="*")

# Dicionário para armazenar chats ativos em memória
active_chats = {}

def get_user_chat():
    """
    Obtém ou cria uma sessão de chat para o usuário.
    Usa flask.session para persistir o session_id do usuário entre conexões/eventos SocketIO.
    """
    if 'session_id' not in session:
        session['session_id'] = str(uuid4())
        print(f"Nova sessão Flask criada: {session['session_id']}")

    session_id = session['session_id']

    if session_id not in active_chats:
        print(f"Criando novo chat Gemini para session_id: {session_id}")
        try:
            chat_session = client.chats.create(
                model="gemini-3.1-flash-lite", # Certifique-se que este modelo suporta chat contínuo
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            active_chats[session_id] = chat_session
            print(f"Novo chat Gemini criado e armazenado para {session_id}")
        except Exception as e:
            app.logger.error(f"Erro ao criar chat Gemini para {session_id}: {e}", exc_info=True)
            # Poderia emitir um erro para o cliente aqui se este erro for crítico para a conexão inicial
            raise  # Re-lança a exceção para ser tratada pelo chamador
    
    # Verifica se o chat não foi perdido (ex. reinício do active_chats mas sessão Flask persistiu)
    if session_id in active_chats and active_chats[session_id] is None:
        print(f"Recriando chat Gemini para session_id existente (estava None): {session_id}")
        try:
            chat_session = client.chats.create(
                model="gemini-2.0-flash-lite",
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            active_chats[session_id] = chat_session
        except Exception as e:
            app.logger.error(f"Erro ao recriar chat Gemini para {session_id}: {e}", exc_info=True)
            raise


    return active_chats[session_id]

@socketio.on('connect')
def handle_connect():
    """
    Chamado quando um cliente se conecta via WebSocket.
    """
    print(f"Cliente conectado: {request.sid}")
    # Tenta obter/criar o chat ao conectar para inicializar a sessão Flask se necessário
    try:
        get_user_chat()
        user_session_id = session.get('session_id', 'N/A')
        print(f"Sessão Flask para {request.sid} usa session_id: {user_session_id}")
        emit('status_conexao', {'data': 'Conectado com sucesso!', 'session_id': user_session_id})
    except Exception as e:
        app.logger.error(f"Erro durante o evento connect para {request.sid}: {e}", exc_info=True)
        emit('erro', {'erro': 'Falha ao inicializar a sessão de chat no servidor.'})


@socketio.on('enviar_mensagem')
def handle_enviar_mensagem(data):
    """
    Manipulador para o evento 'enviar_mensagem' emitido pelo cliente.
    'data' deve ser um dicionário, por exemplo: {'mensagem': 'Olá, mundo!'}
    """
    try:
        mensagem_usuario = data.get("mensagem")
        app.logger.info(f"Mensagem recebida de {session.get('session_id', request.sid)}: {mensagem_usuario}")

        if not mensagem_usuario:
            emit('erro', {"erro": "Mensagem não pode ser vazia."})
            return

        user_chat = get_user_chat()
        if user_chat is None:
            emit('erro', {"erro": "Sessão de chat não pôde ser estabelecida."})
            return

        # Envia a mensagem para o Gemini
        resposta_gemini = user_chat.send_message(mensagem_usuario)

        # Extrai o texto da resposta
        resposta_texto = (
            resposta_gemini.text
            if hasattr(resposta_gemini, 'text')
            else resposta_gemini.candidates[0].content.parts[0].text
        )
        
        # Emite a resposta de volta para o cliente que enviou a mensagem
        emit('nova_mensagem', {"remetente": "bot", "texto": resposta_texto, "session_id": session.get('session_id')})
        app.logger.info(f"Resposta enviada para {session.get('session_id', request.sid)}: {resposta_texto}")

    except Exception as e:
        app.logger.error(f"Erro ao processar 'enviar_mensagem' para {session.get('session_id', request.sid)}: {e}", exc_info=True)
        emit('erro', {"erro": f"Ocorreu um erro no servidor: {str(e)}"})

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Cliente desconectado: {request.sid}, session_id: {session.get('session_id', 'N/A')}")


if __name__ == "__main__":
    socketio.run(app, debug=True)