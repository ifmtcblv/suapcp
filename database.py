import sqlite3
import os
import csv
import hashlib
import logging
import platform
from pathlib import Path

logger = logging.getLogger(__name__)


def get_data_dir() -> Path:
    """Retorna o diretório de dados apropriado com base no sistema operacional."""
    if platform.system() == "Windows":
        data_dir = Path(os.getenv("APPDATA")) / "SUAP-CP"
    else:
        data_dir = Path.home() / ".local" / "share" / "suapcp"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class DatabaseManager:
    def __init__(self, db_path=None):
        self.conn = None
        self.cursor = None
        self._db_path = Path(db_path) if db_path else None
        self.init_database()

    def init_database(self):
        """Inicializa o banco de dados e armazena a conexão e o cursor."""
        db_path = self._db_path if self._db_path else get_data_dir() / "suap.db"

        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.cursor = self.conn.cursor()

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS salas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sala TEXT NOT NULL UNIQUE,
                codigo TEXT NOT NULL UNIQUE
            )
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS patrimonios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero TEXT NOT NULL,
                status TEXT,
                ed TEXT,
                descricao TEXT,
                rotulos TEXT,
                carga_atual TEXT,
                setor_responsavel TEXT,
                campus_carga TEXT,
                valor_aquisicao REAL,
                valor_depreciado REAL,
                numero_nota_fiscal TEXT,
                numero_de_serie TEXT,
                data_da_entrada TEXT,
                data_da_carga TEXT,
                fornecedor TEXT,
                sala_id INTEGER,
                estado_de_conservacao TEXT,
                encontrado INTEGER DEFAULT 0,
                sala_id_original INTEGER,
                FOREIGN KEY (sala_id) REFERENCES salas(id),
                FOREIGN KEY (sala_id_original) REFERENCES salas(id)
            )
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS patrimonios_nao_cadastrados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero TEXT NOT NULL,
                sala_id INTEGER,
                FOREIGN KEY (sala_id) REFERENCES salas(id)
            )
        ''')

        # Índices para consultas frequentes
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_patrimonios_numero ON patrimonios(numero)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_patrimonios_sala_id ON patrimonios(sala_id)"
        )

        # Migração de schema: adiciona colunas se não existirem
        self.cursor.execute("PRAGMA table_info(patrimonios)")
        columns = [col[1] for col in self.cursor.fetchall()]
        if 'encontrado' not in columns:
            self.cursor.execute(
                "ALTER TABLE patrimonios ADD COLUMN encontrado INTEGER DEFAULT 0"
            )
        if 'sala_id_original' not in columns:
            self.cursor.execute(
                "ALTER TABLE patrimonios ADD COLUMN sala_id_original INTEGER"
            )
            self.cursor.execute(
                "UPDATE patrimonios SET sala_id_original = sala_id WHERE sala_id_original IS NULL"
            )

        self.conn.commit()

    def close(self):
        """Fecha a conexão com o banco de dados de forma segura."""
        try:
            if self.conn is not None:
                self.conn.commit()
                self.conn.close()
                self.conn = None
                self.cursor = None
        except Exception as e:
            logger.error("Erro ao fechar a conexão com o banco: %s", e)

    def get_all_salas(self):
        """Retorna uma lista de todas as salas (id, nome)."""
        self.cursor.execute("SELECT id, sala FROM salas ORDER BY sala")
        return self.cursor.fetchall()

    def get_patrimonios_by_sala(self, sala_id):
        """Retorna patrimônios da sala com nome da sala original resolvido via JOIN.

        Retorna 13 colunas:
          numero, status, ed, descricao, rotulos, carga_atual,
          setor_responsavel, campus_carga, numero_de_serie,
          estado_de_conservacao, encontrado, sala_id_original, sala_original_nome
        """
        self.cursor.execute('''
            SELECT p.numero, p.status, p.ed, p.descricao, p.rotulos, p.carga_atual,
                   p.setor_responsavel, p.campus_carga, p.numero_de_serie,
                   p.estado_de_conservacao, p.encontrado, p.sala_id_original,
                   COALESCE(s_orig.sala, '') AS sala_original_nome
            FROM patrimonios p
            LEFT JOIN salas s_orig ON p.sala_id_original = s_orig.id
            WHERE p.sala_id = ?
        ''', (sala_id,))
        return self.cursor.fetchall()

    def mark_patrimonio_encontrado(self, numero, sala_id):
        """Marca um patrimônio como encontrado e atualiza sala_id se necessário."""
        self.cursor.execute(
            "SELECT sala_id, sala_id_original FROM patrimonios WHERE numero = ?",
            (numero,)
        )
        result = self.cursor.fetchone()

        if result:
            current_sala_id, current_sala_id_original = result
            if current_sala_id_original is None:
                self.cursor.execute(
                    "UPDATE patrimonios SET sala_id_original = ? WHERE numero = ?",
                    (current_sala_id, numero)
                )
            self.cursor.execute(
                "UPDATE patrimonios SET sala_id = ?, encontrado = 1 WHERE numero = ?",
                (sala_id, numero)
            )
            self.conn.commit()
            return self.cursor.rowcount > 0
        return False

    def record_unfound_patrimonio(self, numero, sala_id):
        """Registra um patrimônio não cadastrado na tabela patrimonios_nao_cadastrados."""
        self.cursor.execute(
            "INSERT INTO patrimonios_nao_cadastrados (numero, sala_id) VALUES (?, ?)",
            (numero, sala_id)
        )
        self.conn.commit()
        return self.cursor.rowcount > 0

    def get_unfound_patrimonios(self):
        """Retorna todos os patrimônios não cadastrados com suas salas."""
        self.cursor.execute('''
            SELECT s.id, s.sala, u.numero
            FROM patrimonios_nao_cadastrados u
            JOIN salas s ON u.sala_id = s.id
            ORDER BY s.sala, u.numero
        ''')
        return self.cursor.fetchall()

    def get_relatorio_patrimonios(self):
        """Retorna uma lista de todas as salas e seus patrimônios para relatório."""
        self.cursor.execute('''
            SELECT s.id, s.sala, p.numero, p.status, p.ed, p.descricao, p.rotulos,
                   p.carga_atual, p.setor_responsavel, p.campus_carga,
                   p.numero_de_serie, p.estado_de_conservacao, p.encontrado,
                   p.sala_id_original
            FROM salas s
            LEFT JOIN patrimonios p ON s.id = p.sala_id
            ORDER BY s.sala, p.numero
        ''')
        return self.cursor.fetchall()


def generate_unique_code(sala_text, existing_codes=None):
    """Gera um código único baseado no hash MD5 do texto da sala."""
    if not sala_text:
        return None
    code = hashlib.md5(sala_text.encode('utf-8')).hexdigest()
    if existing_codes is None or code not in existing_codes:
        return code
    raise ValueError(f"Colisão de hash MD5 para a sala: {sala_text}")


def _fix_shifted_row(row):
    """Corrige linha com DESCRICAO partida por vírgula não escapada na exportação do SUAP.

    O SUAP às vezes exporta a DESCRICAO sem aspas quando contém vírgula, criando
    um campo extra que desloca todos os campos seguintes 1 posição para a direita.
    Detecta a condição (VALOR AQUISIÇÃO não numérico) e realinha os campos.
    """
    val = row.get('VALOR AQUISIÇÃO', '')
    if not val:
        return row
    try:
        float(val)
        return row
    except ValueError:
        pass
    logger.warning(
        "Deslocamento de campos detectado no patrimônio %s — DESCRICAO partida por vírgula. Corrigindo.",
        row.get('NUMERO', '?'),
    )
    return {
        '#': row['#'],
        'NUMERO': row['NUMERO'],
        'STATUS': row['STATUS'],
        'ED': row['ED'],
        'DESCRICAO': (row['DESCRICAO'] or '') + ', ' + (row['RÓTULOS'] or '').strip(),
        'RÓTULOS': row['CARGA ATUAL'],
        'CARGA ATUAL': row['SETOR DO RESPONSÁVEL'],
        'SETOR DO RESPONSÁVEL': row['CAMPUS DA CARGA'],
        'CAMPUS DA CARGA': row['VALOR AQUISIÇÃO'],
        'VALOR AQUISIÇÃO': row['VALOR DEPRECIADO'],
        'VALOR DEPRECIADO': row['NUMERO NOTA FISCAL'],
        'NUMERO NOTA FISCAL': row['NÚMERO DE SÉRIE'],
        'NÚMERO DE SÉRIE': row['DATA DA ENTRADA'],
        'DATA DA ENTRADA': row['DATA DA CARGA'],
        'DATA DA CARGA': row['FORNECEDOR'],
        'FORNECEDOR': row['SALA'],
        'SALA': row['ESTADO DE CONSERVAÇÃO'],
        'ESTADO DE CONSERVAÇÃO': row.get('', ''),
        '': '',
    }


def _parse_csv(file_path):
    """Lê e valida o CSV completamente em memória.

    Retorna (sala_data, patrimonios_data) em caso de sucesso.
    Lança ValueError se o formato for inválido.
    """
    expected_columns = [
        '#', 'NUMERO', 'STATUS', 'ED', 'DESCRICAO', 'RÓTULOS',
        'CARGA ATUAL', 'SETOR DO RESPONSÁVEL', 'CAMPUS DA CARGA',
        'VALOR AQUISIÇÃO', 'VALOR DEPRECIADO', 'NUMERO NOTA FISCAL',
        'NÚMERO DE SÉRIE', 'DATA DA ENTRADA', 'DATA DA CARGA',
        'FORNECEDOR', 'SALA', 'ESTADO DE CONSERVAÇÃO'
    ]

    with open(file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        fieldnames = [f for f in (reader.fieldnames or []) if f]
        if fieldnames != expected_columns:
            raise ValueError(
                f"Colunas inválidas.\nEsperado: {expected_columns}\nEncontrado: {fieldnames}"
            )

        salas_unicas = set(
            r['SALA'].upper()
            for row in reader
            if (r := _fix_shifted_row(row))['SALA'] and r['SALA'].strip()
        )

        sala_data = []
        existing_codes: set = set()
        sala_to_id: dict = {}
        for next_id, sala in enumerate(salas_unicas, start=1):
            codigo = generate_unique_code(sala, existing_codes)
            existing_codes.add(codigo)
            sala_data.append({'id': next_id, 'sala': sala, 'codigo': codigo})
            sala_to_id[sala] = next_id

        patrimonios_data = []
        csvfile.seek(0)
        next(reader)  # pular cabeçalho
        fixed_count = 0
        for i, raw_row in enumerate(reader, start=1):
            row = _fix_shifted_row(raw_row)
            if row is not raw_row:
                fixed_count += 1
            campus_carga = row['CAMPUS DA CARGA'].lower() if row['CAMPUS DA CARGA'] else None
            sala_text = row['SALA'].upper() if row['SALA'] and row['SALA'].strip() else None
            sala_id = sala_to_id.get(sala_text)
            patrimonios_data.append((
                row['NUMERO'],
                row['STATUS'] or None,
                row['ED'] or None,
                row['DESCRICAO'] or None,
                row['RÓTULOS'] or None,
                row['CARGA ATUAL'] or None,
                row['SETOR DO RESPONSÁVEL'] or None,
                campus_carga,
                float(row['VALOR AQUISIÇÃO']) if row['VALOR AQUISIÇÃO'] else None,
                float(row['VALOR DEPRECIADO']) if row['VALOR DEPRECIADO'] else None,
                row['NUMERO NOTA FISCAL'] or None,
                row['NÚMERO DE SÉRIE'] or None,
                row['DATA DA ENTRADA'] or None,
                row['DATA DA CARGA'] or None,
                row['FORNECEDOR'] or None,
                sala_id,
                row['ESTADO DE CONSERVAÇÃO'] or None,
                0,
                sala_id,
            ))
            if i % 1000 == 0:
                logger.info("Lendo CSV: %d itens processados...", i)

    if fixed_count:
        logger.warning("%d linha(s) com deslocamento de campos corrigida(s).", fixed_count)

    return sala_data, patrimonios_data


def load_data_from_file(cursor, conn, file_path):
    """Valida o CSV e, apenas após parsing bem-sucedido, substitui os dados no banco."""
    logger.info("Iniciando leitura do arquivo: %s", file_path)

    # Fase 1: ler e validar o CSV completamente em memória (banco não é tocado)
    try:
        sala_data, patrimonios_data = _parse_csv(file_path)
    except ValueError as e:
        logger.error("Validação do CSV falhou: %s", e)
        print(f"Erro: {e}")
        return
    except Exception as e:
        logger.error("Erro ao ler o arquivo: %s", e)
        print(f"Erro ao ler o arquivo: {e}")
        return

    # Fase 2: substituir dados no banco (apenas após parsing sem erros)
    try:
        cursor.execute("DELETE FROM patrimonios")
        cursor.execute("DELETE FROM patrimonios_nao_cadastrados")
        cursor.execute("DELETE FROM salas")

        for sala in sala_data:
            cursor.execute(
                "INSERT INTO salas (id, sala, codigo) VALUES (?, ?, ?)",
                (sala['id'], sala['sala'], sala['codigo'])
            )

        cursor.executemany('''
            INSERT INTO patrimonios (
                numero, status, ed, descricao, rotulos, carga_atual,
                setor_responsavel, campus_carga, valor_aquisicao,
                valor_depreciado, numero_nota_fiscal, numero_de_serie,
                data_da_entrada, data_da_carga, fornecedor, sala_id,
                estado_de_conservacao, encontrado, sala_id_original
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', patrimonios_data)

        conn.commit()
        logger.info(
            "Dados carregados com sucesso de %s — %d itens, %d salas",
            file_path, len(patrimonios_data), len(sala_data)
        )
        print(f"Dados carregados com sucesso de {file_path}")
        print(f"Itens importados: {len(patrimonios_data)}")
        print(f"Salas importadas: {len(sala_data)}")
    except Exception as e:
        conn.rollback()
        logger.error("Erro ao gravar no banco: %s", e)
        print(f"Erro ao gravar no banco: {e}")
