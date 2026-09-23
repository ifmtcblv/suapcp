import csv
import hashlib
import io
import logging
import os
import platform
import re
import sqlite3
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

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

    def get_sala_stats(self):
        """Retorna estatísticas de progresso por sala: (id, nome, total, encontrados)."""
        self.cursor.execute('''
            SELECT s.id, s.sala,
                   COUNT(p.id) AS total,
                   COALESCE(SUM(p.encontrado), 0) AS encontrados
            FROM salas s
            LEFT JOIN patrimonios p ON s.id = p.sala_id
            GROUP BY s.id, s.sala
            ORDER BY s.sala
        ''')
        return self.cursor.fetchall()

    def get_patrimonio_status(self, numero):
        """Retorna (encontrado, sala_id) do patrimônio ou None se não cadastrado."""
        self.cursor.execute(
            "SELECT encontrado, sala_id FROM patrimonios WHERE numero = ?",
            (numero,)
        )
        return self.cursor.fetchone()

    def search_patrimonio(self, numero):
        """Busca patrimônios pelo número (busca parcial), retornando dados e salas.

        Retorna até 200 resultados com 14 colunas:
          numero, status, ed, descricao, rotulos, carga_atual,
          setor_responsavel, campus_carga, numero_de_serie,
          estado_de_conservacao, encontrado, sala_id_original,
          sala_original_nome, sala_atual_nome
        """
        self.cursor.execute('''
            SELECT p.numero, p.status, p.ed, p.descricao, p.rotulos, p.carga_atual,
                   p.setor_responsavel, p.campus_carga, p.numero_de_serie,
                   p.estado_de_conservacao, p.encontrado, p.sala_id_original,
                   COALESCE(s_orig.sala, '') AS sala_original_nome,
                   COALESCE(s_atual.sala, '') AS sala_atual_nome
            FROM patrimonios p
            LEFT JOIN salas s_orig ON p.sala_id_original = s_orig.id
            LEFT JOIN salas s_atual ON p.sala_id = s_atual.id
            WHERE p.numero LIKE ?
            ORDER BY p.numero
            LIMIT 200
        ''', (f'%{numero}%',))
        return self.cursor.fetchall()


def generate_unique_code(sala_text, existing_codes=None):
    """Gera um código único baseado no hash MD5 do texto da sala."""
    if not sala_text:
        return None
    code = hashlib.md5(sala_text.encode('utf-8')).hexdigest()
    if existing_codes is None or code not in existing_codes:
        return code
    raise ValueError(f"Colisão de hash MD5 para a sala: {sala_text}")


# Colunas usadas pela conferência. A exportação do SUAP é lida pelo nome,
# então colunas extras ou reordenadas não deslocam os campos.
EXPECTED_COLUMNS = [
    '#', 'NUMERO', 'STATUS', 'ED', 'DESCRICAO', 'RÓTULOS',
    'CARGA ATUAL', 'SETOR DO RESPONSÁVEL', 'CAMPUS DA CARGA',
    'VALOR AQUISIÇÃO', 'VALOR DEPRECIADO', 'NUMERO NOTA FISCAL',
    'NÚMERO DE SÉRIE', 'DATA DA ENTRADA', 'DATA DA CARGA',
    'FORNECEDOR', 'SALA', 'ESTADO DE CONSERVAÇÃO',
]

_SALA_SEM_LOCAL = "SEM SALA"
_EMPTY_MARKERS = {"-", "—", "–"}

_SSML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _clean(value: object) -> str:
    """Normaliza célula da exportação. O SUAP usa '-' como vazio."""
    if value is None:
        return ""
    text = str(value).strip()
    if text in _EMPTY_MARKERS:
        return ""
    return text


def _parse_decimal(value: object) -> float | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        if "," in text:
            return float(text.replace(".", "").replace(",", "."))
        raise


def _fix_shifted_row(row):
    """Corrige linha com DESCRICAO partida por vírgula não escapada na exportação do SUAP.

    O SUAP às vezes exporta a DESCRICAO sem aspas quando contém vírgula, criando
    um campo extra que desloca todos os campos seguintes 1 posição para a direita.
    Detecta a condição (VALOR AQUISIÇÃO não numérico) e realinha os campos.
    """
    val = _clean(row.get('VALOR AQUISIÇÃO', ''))
    if not val:
        return row
    try:
        float(val.replace(".", "").replace(",", ".") if "," in val else val)
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


def _validate_columns(fieldnames: list[str]) -> None:
    missing = [column for column in EXPECTED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(
            "Colunas ausentes na exportação do SUAP.\n"
            f"Ausentes: {missing}\n"
            f"Encontrado: {fieldnames}"
        )


def _is_footer(row: dict[str, str]) -> bool:
    """Ignora o rodapé de totais que o SUAP acrescenta depois dos itens."""
    if _clean(row.get("NUMERO")):
        return False
    return any(_clean(value).upper() == "TOTAL" for value in row.values())


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_csv_rows(file_path: str) -> tuple[list[str], list[dict[str, str]]]:
    text = _decode_text(Path(file_path).read_bytes())
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fieldnames = [name for name in (reader.fieldnames or []) if name]
    rows = [
        {key: value or "" for key, value in raw.items() if key}
        for raw in reader
    ]
    return fieldnames, rows


def _column_index(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - 64)
    return index - 1


_XLSX_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")


def _unescape_xlsx(text: str) -> str:
    """Converte escapes do Excel, como ``_x000D_``, de volta para o caractere."""
    protected = text.replace("_x005F_", "\u0000")

    def replace(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    return _XLSX_ESCAPE.sub(replace, protected).replace("\u0000", "_")


def _xlsx_cell_text(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return _unescape_xlsx(
            "".join(node.text or "" for node in cell.iter(f"{{{_SSML}}}t"))
        )
    value = cell.find(f"{{{_SSML}}}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        return _unescape_xlsx(shared[int(value.text)])
    if cell_type == "b":
        return "TRUE" if value.text == "1" else "FALSE"
    text = value.text
    if "." in text:
        try:
            number = float(text)
        except ValueError:
            return text
        if number.is_integer():
            return str(int(number))
    return text


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheets = workbook.findall(f"{{{_SSML}}}sheets/{{{_SSML}}}sheet")
    if not sheets:
        raise ValueError("A planilha não contém abas.")
    rel_id = sheets[0].attrib.get(f"{{{_OFFICE_REL}}}id")
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for rel in rels:
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target", "worksheets/sheet1.xml")
            if target.startswith("/"):
                return target.lstrip("/")
            if target.startswith("xl/"):
                return target
            return f"xl/{target}"
    return "xl/worksheets/sheet1.xml"


def _read_xlsx_rows(file_path: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        archive = zipfile.ZipFile(file_path)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Arquivo XLSX inválido: {exc}") from exc

    with archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{{{_SSML}}}si"):
                shared.append(
                    "".join(node.text or "" for node in item.iter(f"{{{_SSML}}}t"))
                )
        sheet = ET.fromstring(archive.read(_first_sheet_path(archive)))

    table: list[list[str]] = []
    for row in sheet.findall(f".//{{{_SSML}}}sheetData/{{{_SSML}}}row"):
        cells: dict[int, str] = {}
        for cell in row.findall(f"{{{_SSML}}}c"):
            ref = cell.attrib.get("r", "")
            index = _column_index(ref) if ref else len(cells)
            cells[index] = _xlsx_cell_text(cell, shared)
        if not cells or not any(value.strip() for value in cells.values()):
            continue
        width = max(cells) + 1
        table.append([cells.get(index, "") for index in range(width)])

    if not table:
        raise ValueError("A planilha está vazia.")

    fieldnames = [name.strip() for name in table[0] if name.strip()]
    rows: list[dict[str, str]] = []
    for raw in table[1:]:
        rows.append({
            name: raw[index] if index < len(raw) else ""
            for index, name in enumerate(table[0])
            if name.strip()
        })
    return fieldnames, rows


def _read_export_rows(file_path: str) -> tuple[list[str], list[dict[str, str]]]:
    suffix = Path(file_path).suffix.lower()
    if suffix == ".csv":
        return _read_csv_rows(file_path)
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx_rows(file_path)
    raise ValueError(
        f"Formato não suportado ({suffix or 'sem extensão'}). "
        "Use um arquivo .csv ou .xlsx."
    )


def _parse_export(file_path: str):
    """Lê e valida uma exportação CSV ou XLSX do SUAP.

    Retorna (sala_data, patrimonios_data) em caso de sucesso.
    Lança ValueError se o formato for inválido.
    """
    fieldnames, rows = _read_export_rows(file_path)
    _validate_columns(fieldnames)

    parsed: list[dict[str, str | float | None]] = []
    fixed_count = 0
    for index, raw_row in enumerate(rows, start=1):
        if _is_footer(raw_row):
            continue
        row = _fix_shifted_row(raw_row)
        if row is not raw_row:
            fixed_count += 1
        numero = _clean(row.get("NUMERO"))
        if not numero:
            continue
        sala = _clean(row.get("SALA")).upper() or _SALA_SEM_LOCAL
        campus = _clean(row.get("CAMPUS DA CARGA"))
        parsed.append({
            "numero": numero,
            "status": _clean(row.get("STATUS")) or None,
            "ed": _clean(row.get("ED")) or None,
            "descricao": _clean(row.get("DESCRICAO")) or None,
            "rotulos": _clean(row.get("RÓTULOS")) or None,
            "carga_atual": _clean(row.get("CARGA ATUAL")) or None,
            "setor_responsavel": _clean(row.get("SETOR DO RESPONSÁVEL")) or None,
            "campus_carga": campus.lower() if campus else None,
            "valor_aquisicao": _parse_decimal(row.get("VALOR AQUISIÇÃO")),
            "valor_depreciado": _parse_decimal(row.get("VALOR DEPRECIADO")),
            "numero_nota_fiscal": _clean(row.get("NUMERO NOTA FISCAL")) or None,
            "numero_de_serie": _clean(row.get("NÚMERO DE SÉRIE")) or None,
            "data_da_entrada": _clean(row.get("DATA DA ENTRADA")) or None,
            "data_da_carga": _clean(row.get("DATA DA CARGA")) or None,
            "fornecedor": _clean(row.get("FORNECEDOR")) or None,
            "sala": sala,
            "estado_de_conservacao": _clean(row.get("ESTADO DE CONSERVAÇÃO")) or None,
        })
        if index % 1000 == 0:
            logger.info("Lendo exportação: %d linhas processadas...", index)

    if fixed_count:
        logger.warning(
            "%d linha(s) com deslocamento de campos corrigida(s).",
            fixed_count,
        )

    sala_data = []
    existing_codes: set[str] = set()
    sala_to_id: dict[str, int] = {}
    for item in parsed:
        sala = str(item["sala"])
        if sala in sala_to_id:
            continue
        codigo = generate_unique_code(sala, existing_codes)
        if codigo is None:
            raise ValueError(f"Não foi possível gerar código para a sala: {sala}")
        existing_codes.add(codigo)
        next_id = len(sala_data) + 1
        sala_data.append({"id": next_id, "sala": sala, "codigo": codigo})
        sala_to_id[sala] = next_id

    patrimonios_data = [
        (
            item["numero"],
            item["status"],
            item["ed"],
            item["descricao"],
            item["rotulos"],
            item["carga_atual"],
            item["setor_responsavel"],
            item["campus_carga"],
            item["valor_aquisicao"],
            item["valor_depreciado"],
            item["numero_nota_fiscal"],
            item["numero_de_serie"],
            item["data_da_entrada"],
            item["data_da_carga"],
            item["fornecedor"],
            sala_to_id[str(item["sala"])],
            item["estado_de_conservacao"],
            0,
            sala_to_id[str(item["sala"])],
        )
        for item in parsed
    ]
    return sala_data, patrimonios_data


def load_data_from_file(cursor, conn, file_path):
    """Valida a exportação e, se estiver correta, substitui os dados no banco."""
    logger.info("Iniciando leitura do arquivo: %s", file_path)

    # Fase 1: ler e validar completamente em memória (banco não é tocado)
    try:
        sala_data, patrimonios_data = _parse_export(file_path)
    except ValueError as e:
        logger.error("Validação da exportação falhou: %s", e)
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
