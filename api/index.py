import os
from datetime import date, datetime

import psycopg
from psycopg.rows import dict_row
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# Caminho para localizar a pasta templates na raiz do projeto
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates'))
app = Flask(__name__, template_folder=template_dir) 

# Chave secreta necessária para gerenciar sessões
# Em produção, nunca use uma chave fixa no código-fonte.
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'chave_secreta-agenda-local')

# Usuários padrão (ativo=True libera o acesso)
USUARIOS = {'admin': {'senha': 'admin123', 'role': 'admin', 'ativo': True}}

# String de conexão com o banco Neon (injetada pela integração)
DATABASE_URL = os.environ.get('DATABASE_URL')

# A agenda é persistida no Neon; não manter estado de negócio em memória.


# --- BANCO DE DADOS (TÉCNICOS) ---


def get_conn():
  """Abre uma nova conexão com o banco Neon."""
  return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
  """Garante que a tabela de técnicos exista."""
  with get_conn() as conn:
    with conn.cursor() as cur:
      cur.execute(
          'CREATE TABLE IF NOT EXISTS tecnicos ('
          'id SERIAL PRIMARY KEY, '
          'nome TEXT UNIQUE NOT NULL, '
          'criado_em TIMESTAMPTZ DEFAULT now())'
      )
      cur.execute(
          'CREATE TABLE IF NOT EXISTS avisos ('
          'id SERIAL PRIMARY KEY, '
          'mensagem TEXT NOT NULL, '
          'criado_em TIMESTAMPTZ DEFAULT now())'
      )
      conn.commit()


def listar_tecnicos():
  with get_conn() as conn:
    with conn.cursor() as cur:
      cur.execute('SELECT nome FROM tecnicos ORDER BY id')
      return [linha['nome'] for linha in cur.fetchall()]


def adicionar_tecnico(nome):
  with get_conn() as conn:
    with conn.cursor() as cur:
      cur.execute(
          'INSERT INTO tecnicos (nome) VALUES (%s) '
          'ON CONFLICT (nome) DO NOTHING',
          (nome,),
      )
      conn.commit()


def remover_tecnico(nome):
  with get_conn() as conn:
    with conn.cursor() as cur:
      cur.execute('DELETE FROM tecnicos WHERE nome = %s', (nome,))
      conn.commit()


# --- BANCO DE DADOS (AVISOS) ---


def listar_avisos():
  """Retorna todos os avisos cadastrados (para rodar em loop no visualizador)."""
  with get_conn() as conn:
    with conn.cursor() as cur:
      cur.execute('SELECT id, mensagem, criado_em FROM avisos ORDER BY id')
      return [
          {
              'id': linha['id'],
              'mensagem': linha['mensagem'],
              'criado_em': linha['criado_em'].isoformat()
              if linha['criado_em']
              else None,
          }
          for linha in cur.fetchall()
      ]


def adicionar_aviso(mensagem):
  """Adiciona um novo aviso mantendo os existentes."""
  with get_conn() as conn:
    with conn.cursor() as cur:
      cur.execute('INSERT INTO avisos (mensagem) VALUES (%s)', (mensagem,))
      conn.commit()


def remover_aviso(aviso_id):
  """Remove um aviso específico pelo id."""
  with get_conn() as conn:
    with conn.cursor() as cur:
      cur.execute('DELETE FROM avisos WHERE id = %s', (aviso_id,))
      conn.commit()


def limpar_avisos():
  """Remove todos os avisos."""
  with get_conn() as conn:
    with conn.cursor() as cur:
      cur.execute('DELETE FROM avisos')
      conn.commit()


# Cria a tabela na inicialização (idempotente)
try:
  init_db()
except Exception as e:  # noqa: BLE001
  print('[v0] Falha ao inicializar o banco de tecnicos:', e)


# --- ROTAS DE AUTENTICAÇÃO E NAVEGAÇÃO ---


@app.route('/')
def home():
  # Se já estiver logado, vai direto para a index. Caso contrário, vai para o login.
  if 'usuario' in session:
    return redirect(url_for('index_page'))
  return redirect(url_for('login_page'))


@app.route('/login', methods=['GET', 'POST'])
def login_page():
  # Se tentar acessar a tela de login já estando autenticado via GET, redireciona para a index
  if 'usuario' in session and request.method == 'GET':
    return redirect(url_for('index_page'))

  erro = None
  sucesso = None

  if request.method == 'POST':
    acao = request.form.get('acao')

    # LOGIN
    if acao == 'entrar':
      usuario = request.form.get('username', '').strip()
      senha = request.form.get('password', '').strip()

      if usuario in USUARIOS and USUARIOS[usuario]['senha'] == senha:
        if not USUARIOS[usuario]['ativo']:
          erro = 'Sua conta ainda não foi liberada pelo Administrador.'
        else:
          session['usuario'] = usuario
          session['role'] = USUARIOS[usuario]['role']
          return redirect(url_for('index_page'))
      else:
        erro = 'Usuário ou senha incorretos!'

    # CADASTRO
    elif acao == 'cadastrar':
      novo_usuario = request.form.get('new_username', '').strip()
      nova_senha = request.form.get('new_password', '').strip()

      if not novo_usuario or not nova_senha:
        erro = 'Preencha todos os campos.'
      elif novo_usuario in USUARIOS:
        erro = 'Este nome de usuário já existe!'
      else:
        USUARIOS[novo_usuario] = {
            'senha': nova_senha,
            'role': 'user',
            'ativo': False,
        }
        sucesso = (
            'Cadastro realizado! Aguarde o Administrador liberar seu acesso.'
        )

  return render_template('login.html', erro=erro, sucesso=sucesso)


@app.route('/logout')
def logout():
  # Limpa toda a sessão ativa (remove o usuário logado)
  session.clear()
  return redirect(url_for('login_page'))


# --- ROTAS PRINCIPAIS ---


@app.route('/index')
def index_page():
  if 'usuario' not in session:
    return redirect(url_for('login_page'))

  data_hoje = date.today().strftime('%Y-%m-%d')
  return render_template(
      'index.html',
      data_inicial=data_hoje,
      usuario_logado=session['usuario'],
      e_admin=(session.get('role') == 'admin'),
  )


@app.route('/admin')
def admin_page():
  if 'usuario' not in session or session.get('role') != 'admin':
    return (
        'Acesso negado: Apenas o Administrador pode acessar esta página.',
        403,
    )

  return render_template('admin.html', usuarios=USUARIOS)


@app.route('/visualizador')
def visualizador():
  data_inicial = datetime.now().strftime('%Y-%m-%d')
  return render_template('visualizador.html', data_inicial=data_inicial)


# --- APIS DO SISTEMA ---


@app.route('/admin/toggle-status', methods=['POST'])
def toggle_status():
  if 'usuario' not in session or session.get('role') != 'admin':
    return jsonify({'error': 'Não autorizado'}), 403

  payload = request.get_json(silent=True) or {}
  usuario_alvo = (payload.get('usuario') or '').strip()
  if usuario_alvo in USUARIOS and usuario_alvo != 'admin':
    USUARIOS[usuario_alvo]['ativo'] = not USUARIOS[usuario_alvo]['ativo']
    return jsonify(
        {'success': True, 'novo_status': USUARIOS[usuario_alvo]['ativo']}
    )

  return jsonify({'error': 'Ação inválida'}), 400


@app.route('/api/tecnicos', methods=['GET', 'POST', 'DELETE'])
def api_tecnicos():
  # Consulta pública permitida para o visualizador de agenda
  if request.method == 'GET':
    return jsonify(listar_tecnicos())

  # Apenas criação/remoção exige login e admin
  if 'usuario' not in session:
    return jsonify({'error': 'Não autorizado'}), 401

  if session.get('role') != 'admin':
    return jsonify({'error': 'Ação restrita a Administradores'}), 403

  if request.method == 'POST':
    payload = request.get_json(silent=True) or {}
    nome = (payload.get('nome') or '').strip()
    if nome:
      adicionar_tecnico(nome)
    return jsonify(listar_tecnicos())

  elif request.method == 'DELETE':
    payload = request.get_json(silent=True) or {}
    nome = (payload.get('nome') or '').strip()
    if nome:
      remover_tecnico(nome)
    return jsonify(listar_tecnicos())


# API de Agenda (GET público para consulta do visualizador, POST restrito a admins)
@app.route('/api/agenda', methods=['GET', 'POST'])
def api_agenda():
  if request.method == 'GET':
    data_sel = request.args.get('data', datetime.now().strftime('%Y-%m-%d'))
    with get_conn() as conn:
      with conn.cursor() as cur:
        cur.execute(
            'SELECT chave, status, info FROM agenda WHERE data = %s ORDER BY chave',
            (data_sel,),
        )
        agenda = {
            linha['chave']: {'status': linha['status'], 'info': linha['info']}
            for linha in cur.fetchall()
        }
    return jsonify(agenda)

  if 'usuario' not in session:
    return jsonify({'error': 'Não autorizado'}), 401
  if session.get('role') != 'admin':
    return jsonify({'error': 'Ação restrita a Administradores'}), 403

  payload = request.get_json(silent=True) or {}
  data = (payload.get('data') or '').strip()
  chave = (payload.get('chave') or '').strip()
  status = payload.get('status')
  info = payload.get('info')
  if not data or not chave:
    return jsonify({'error': 'data e chave são obrigatórios'}), 400

  with get_conn() as conn:
    with conn.cursor() as cur:
      cur.execute(
          'INSERT INTO agenda (data, chave, status, info) VALUES (%s, %s, %s, %s) '
          'ON CONFLICT (data, chave) DO UPDATE SET status = EXCLUDED.status, '
          'info = EXCLUDED.info, atualizado_em = now()',
          (data, chave, status, info),
      )
      conn.commit()
  return jsonify({'success': True})


@app.route('/api/aviso', methods=['GET', 'POST', 'DELETE'])
def api_aviso():
  # Consulta pública liberada para o visualizador de agenda
  if request.method == 'GET':
    return jsonify(listar_avisos())

  # Envio/remoção exige login e perfil admin
  if 'usuario' not in session:
    return jsonify({'error': 'Não autorizado'}), 401

  if session.get('role') != 'admin':
    return jsonify({'error': 'Ação restrita a Administradores'}), 403

  if request.method == 'POST':
    payload = request.get_json(silent=True) or {}
    mensagem = (payload.get('mensagem') or '').strip()
    if not mensagem:
      return jsonify({'error': 'mensagem é obrigatória'}), 400
    adicionar_aviso(mensagem)
    return jsonify(listar_avisos())

  elif request.method == 'DELETE':
    limpar_avisos()
    return jsonify(listar_avisos())


if __name__ == '__main__':
  app.run(debug=True)
