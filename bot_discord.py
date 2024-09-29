import os
import discord
from dotenv import load_dotenv
import sqlite3
import requests
from datetime import datetime, timedelta


#tentando calcular o bot


def adapt_datetime(dt):
    return dt.isoformat()

def convert_datetime(s):
    return datetime.fromisoformat(s)

# Carregar variáveis de ambiente
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Configuração do cliente Discord
intents = discord.Intents.default()
intents.message_content = True  # Habilita o acesso ao conteúdo das mensagens
client = discord.Client(intents=intents)

# Configuração do banco de dados SQLite
sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_datetime)
conn = sqlite3.connect('steam_watchlist.db', detect_types=sqlite3.PARSE_DECLTYPES)
cursor = conn.cursor()

# Criação da tabela para armazenar os jogos observados
cursor.execute('''
    CREATE TABLE IF NOT EXISTS watched_games (
        user_id INTEGER,
        game_id INTEGER,
        game_name TEXT,
        current_price REAL,
        last_checked TIMESTAMP
    )
''')
conn.commit()

# Função para enviar mensagens via Discord
async def send_discord_message(channel, message):
    await channel.send(message)

# Função para buscar o ID de um jogo na Steam
def search_game_id(game_name):
    url = f"https://store.steampowered.com/api/storesearch/?term={game_name}&l=portuguese&cc=BR"
    response = requests.get(url)
    data = response.json()
    if data['total'] > 0:
        return data['items'][0]['id']
    return None

# Função para buscar informações de um jogo na Steam
def get_steam_game_info(game_id):
    url = f"https://store.steampowered.com/api/appdetails?appids={game_id}"
    response = requests.get(url)
    data = response.json()
    return data[str(game_id)]['data'] if data[str(game_id)]['success'] else None

# Evento quando o bot está pronto
@client.event
async def on_ready():
    print(f'Bot conectado como {client.user}')

# Evento quando uma mensagem é recebida
@client.event
async def on_message(message):
    if message.author == client.user:
        return
    match message:
        # Comando para mostrar ajuda
        case message.content.startswith('/help'):
            comandos = (
            """ /start - Inicia o bot.\n"
                /add <nome_do_jogo> - Adiciona um jogo à lista de observação.\n
                /check - Verifica os preços dos jogos na sua lista de observação.\n
                /list - Lista os jogos observados.\n
                /remove <nome_do_jogo> - Remove um jogo da lista de observação.\n"""
            )
            await send_discord_message(message.channel, comandos)

        case message.content.startswith('/start'):
            mensagem_boas_vindas = (
            "Olá! Bem-vindo ao Bot de Monitoramento de Preços da Steam.\n\n"
            "Aqui estão os comandos disponíveis:\n"
            "/add <nome_do_jogo> - Adiciona um jogo à sua lista de observação\n"
            "/check - Verifica os preços dos jogos na sua lista\n"
            "/list - Mostra todos os jogos na sua lista de observação\n"
            "/remove <nome_do_jogo> - Remove um jogo da sua lista de observação\n"
        )
            await send_discord_message(message.channel, mensagem_boas_vindas)

        case message.content.startswith('/add'):
            game_name = message.content.split(' ', 1)[1]  # Obtém o nome do jogo
            user_id = message.author.id

            cursor.execute('SELECT * FROM watched_games WHERE user_id = ? AND LOWER(game_name) = LOWER(?)', (user_id, game_name))
            if cursor.fetchone():
                await send_discord_message(message.channel, f"O jogo '{game_name}' já está na sua lista de observação.")
                return

            game_id = search_game_id(game_name)
            if game_id:
                game_info = get_steam_game_info(game_id)
                if game_info:
                    cursor.execute(''' 
                        INSERT INTO watched_games (user_id, game_id, game_name, current_price, last_checked) 
                        VALUES (?, ?, ?, ?, ?) 
                    ''', (user_id, game_id, game_info['name'], game_info['price_overview']['final'] / 100, datetime.now()))
                    conn.commit()
                    await send_discord_message(message.channel, f"Jogo '{game_info['name']}' adicionado à lista de observação.")
                else:
                    await send_discord_message(message.channel, "Não foi possível encontrar informações sobre este jogo.")
            else:
                await send_discord_message(message.channel, "Não foi possível encontrar o jogo. Por favor, verifique o nome e tente novamente.")

        case message.content.startswith('/remove'):
            game_name = message.content.split(' ', 1)[1]  # Obtém o nome do jogo
            user_id = message.author.id
            
            cursor.execute(''' 
                DELETE FROM watched_games 
                WHERE user_id = ? AND LOWER(game_name) = LOWER(?) 
            ''', (user_id, game_name))
            
            if cursor.rowcount > 0:
                conn.commit()
                await send_discord_message(message.channel, f"O jogo '{game_name}' foi removido da sua lista de observação.")
            else:
                await send_discord_message(message.channel, f"Não foi encontrado nenhum jogo com o nome '{game_name}' na sua lista de observação.")

        case message.content.startswith('/check'):
            user_id = message.author.id
            
            cursor.execute(''' 
                SELECT 
                    game_id, 
                    game_name, 
                    CAST(current_price AS REAL), 
                    CAST(last_checked AS TEXT) 
                FROM watched_games 
                WHERE user_id = ? 
            ''', (user_id,))
            watched_games = cursor.fetchall()
            
            if not watched_games:
                await send_discord_message(message.channel, "Você não tem jogos na sua lista de observação.")
                return

            for game_id, game_name, old_price, last_checked in watched_games:
                game_info = get_steam_game_info(game_id)
                if game_info and 'price_overview' in game_info:
                    new_price = game_info['price_overview']['final'] / 100
                    
                    if new_price < old_price:
                        discount = (1 - new_price / old_price) * 100
                        await send_discord_message(message.channel, f"O jogo '{game_name}' está com desconto de {discount:.2f}%! Preço atual: R$ {new_price:.2f}.")
                    else:
                        await send_discord_message(message.channel, f"O jogo '{game_name}' não está em promoção no momento. Preço atual: R$ {new_price:.2f}.")
                    
                    cursor.execute(''' 
                        UPDATE watched_games 
                        SET current_price = ?, last_checked = ? 
                        WHERE user_id = ? AND game_id = ? 
                    ''', (new_price, datetime.now().isoformat(), user_id, game_id))
                    conn.commit()
                else:
                    await send_discord_message(message.channel, f"Não foi possível obter informações atualizadas para o jogo '{game_name}'.")

            await send_discord_message(message.channel, "Verificação de preços concluída.")

        case message.content.startswith('/list'):
            user_id = message.author.id
            
            cursor.execute('SELECT game_name, current_price FROM watched_games WHERE user_id = ?', (user_id,))
            watched_games = cursor.fetchall()
            
            if watched_games:
                message_list = "Seus jogos observados:\n\n"
                for game in watched_games:
                    message_list += f"- {game[0]}: R$ {game[1]:.2f}\n"
                await send_discord_message(message.channel, message_list)
            else:
                await send_discord_message(message.channel, "Você não tem jogos na sua lista de observação.")



# Iniciar o bot do Discord
client.run(DISCORD_TOKEN)
