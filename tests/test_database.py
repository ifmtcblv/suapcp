"""Tests for database.py — unit and integration."""

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from database import (
    DatabaseManager,
    _fix_shifted_row,
    generate_unique_code,
    load_data_from_file,
)

# ---------------------------------------------------------------------------
# generate_unique_code
# ---------------------------------------------------------------------------

class TestGenerateUniqueCode:
    def test_returns_md5_hex(self):
        code = generate_unique_code("SALA 101")
        assert len(code) == 32
        assert all(c in "0123456789abcdef" for c in code)

    def test_same_input_same_code(self):
        assert generate_unique_code("SALA 101") == generate_unique_code("SALA 101")

    def test_different_inputs_different_codes(self):
        assert generate_unique_code("SALA 101") != generate_unique_code("SALA 102")

    def test_none_returns_none(self):
        assert generate_unique_code(None) is None

    def test_empty_string_returns_none(self):
        assert generate_unique_code("") is None

    def test_raises_on_collision(self):
        code = generate_unique_code("SALA 101")
        with pytest.raises(ValueError, match="Colisão"):
            generate_unique_code("SALA 101", existing_codes={code})

    def test_no_raise_when_code_not_in_existing(self):
        code = generate_unique_code("SALA 101", existing_codes={"other_code"})
        assert code is not None


# ---------------------------------------------------------------------------
# _fix_shifted_row
# ---------------------------------------------------------------------------

class TestFixShiftedRow:
    def _make_row(self, valor_aquisicao):
        return {
            '#': '1',
            'NUMERO': '12345',
            'STATUS': 'Ativo',
            'ED': 'ED01',
            'DESCRICAO': 'MESA',
            'RÓTULOS': 'rotulo',
            'CARGA ATUAL': 'SETOR A',
            'SETOR DO RESPONSÁVEL': 'CAMPUS X',
            'CAMPUS DA CARGA': 'BLV',
            'VALOR AQUISIÇÃO': valor_aquisicao,
            'VALOR DEPRECIADO': '100.00',
            'NUMERO NOTA FISCAL': 'NF001',
            'NÚMERO DE SÉRIE': 'SN001',
            'DATA DA ENTRADA': '2020-01-01',
            'DATA DA CARGA': '2020-01-02',
            'FORNECEDOR': 'FORNECEDOR X',
            'SALA': 'SALA 101',
            'ESTADO DE CONSERVAÇÃO': 'Bom',
            '': '',
        }

    def test_no_shift_returns_same_row(self):
        row = self._make_row('500.00')
        result = _fix_shifted_row(row)
        assert result is row

    def test_shift_detected_and_corrected(self):
        row = self._make_row('BLV')  # non-numeric → shifted
        result = _fix_shifted_row(row)
        assert result is not row
        # After correction, VALOR AQUISIÇÃO should be '100.00' (was VALOR DEPRECIADO)
        assert result['VALOR AQUISIÇÃO'] == '100.00'

    def test_shift_concatenates_descricao(self):
        row = self._make_row('BLV')
        row['DESCRICAO'] = 'MARCA'
        row['RÓTULOS'] = 'USE MOVEIS'
        result = _fix_shifted_row(row)
        assert result['DESCRICAO'] == 'MARCA, USE MOVEIS'

    def test_empty_valor_aquisicao_returns_same_row(self):
        row = self._make_row('')
        result = _fix_shifted_row(row)
        assert result is row


# ---------------------------------------------------------------------------
# DatabaseManager
# ---------------------------------------------------------------------------

class TestDatabaseManager:
    def test_init_creates_tables(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in db.cursor.fetchall()}
        assert {"salas", "patrimonios", "patrimonios_nao_cadastrados"}.issubset(tables)
        db.close()

    def test_get_all_salas_empty(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        assert db.get_all_salas() == []
        db.close()

    def test_get_patrimonios_by_sala_empty(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        assert db.get_patrimonios_by_sala(1) == []
        db.close()

    def test_close_idempotent(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.close()
        db.close()  # should not raise

    def test_mark_patrimonio_encontrado(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.cursor.execute("INSERT INTO salas (id, sala, codigo) VALUES (1, 'SALA A', 'abc')")
        db.cursor.execute(
            "INSERT INTO patrimonios (numero, sala_id, encontrado) VALUES ('P001', 1, 0)"
        )
        db.conn.commit()

        result = db.mark_patrimonio_encontrado('P001', 1)
        assert result is True

        db.cursor.execute("SELECT encontrado FROM patrimonios WHERE numero = 'P001'")
        assert db.cursor.fetchone()[0] == 1
        db.close()

    def test_mark_patrimonio_encontrado_nonexistent(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        result = db.mark_patrimonio_encontrado('NONEXISTENT', 1)
        assert result is False
        db.close()

    def test_record_unfound_patrimonio(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.cursor.execute("INSERT INTO salas (id, sala, codigo) VALUES (1, 'SALA A', 'abc')")
        db.conn.commit()

        db.record_unfound_patrimonio('P999', 1)
        rows = db.get_unfound_patrimonios()
        assert len(rows) == 1
        assert rows[0][2] == 'P999'
        db.close()

    def test_get_patrimonios_by_sala_returns_13_fields(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.cursor.execute("INSERT INTO salas (id, sala, codigo) VALUES (1, 'SALA A', 'abc')")
        db.cursor.execute(
            "INSERT INTO patrimonios (numero, sala_id, sala_id_original, encontrado) VALUES ('P001', 1, 1, 0)"
        )
        db.conn.commit()

        rows = db.get_patrimonios_by_sala(1)
        assert len(rows) == 1
        assert len(rows[0]) == 13
        db.close()


# ---------------------------------------------------------------------------
# load_data_from_file
# ---------------------------------------------------------------------------

VALID_HEADERS = (
    '#,NUMERO,STATUS,ED,DESCRICAO,RÓTULOS,CARGA ATUAL,SETOR DO RESPONSÁVEL,'
    'CAMPUS DA CARGA,VALOR AQUISIÇÃO,VALOR DEPRECIADO,NUMERO NOTA FISCAL,'
    'NÚMERO DE SÉRIE,DATA DA ENTRADA,DATA DA CARGA,FORNECEDOR,SALA,ESTADO DE CONSERVAÇÃO,\n'
)

VALID_ROW = (
    '1,P001,Ativo,ED01,Mesa,,SETOR A,RESP A,BLV,500.00,400.00,NF001,'
    'SN001,2020-01-01,2020-01-02,FORN A,SALA 101,Bom,\n'
)


def _make_csv(rows: list[str]) -> str:
    return VALID_HEADERS + "".join(rows)


class TestLoadDataFromFile:
    def test_loads_valid_csv(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(_make_csv([VALID_ROW]), encoding="utf-8")

        db = DatabaseManager(db_path=tmp_path / "test.db")
        load_data_from_file(db.cursor, db.conn, str(csv_path))

        salas = db.get_all_salas()
        assert len(salas) == 1
        assert salas[0][1] == "SALA 101"

        rows = db.get_patrimonios_by_sala(salas[0][0])
        assert len(rows) == 1
        assert rows[0][0] == "P001"
        db.close()

    def test_invalid_csv_does_not_delete_existing_data(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.cursor.execute("INSERT INTO salas (id, sala, codigo) VALUES (1, 'EXISTENTE', 'abc')")
        db.conn.commit()

        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("COL1,COL2\nval1,val2\n", encoding="utf-8")
        load_data_from_file(db.cursor, db.conn, str(bad_csv))

        salas = db.get_all_salas()
        assert len(salas) == 1
        assert salas[0][1] == "EXISTENTE"
        db.close()

    def test_multiple_salas(self, tmp_path):
        row2 = (
            '2,P002,Ativo,ED01,Cadeira,,SETOR B,RESP B,BLV,200.00,150.00,NF002,'
            'SN002,2020-02-01,2020-02-02,FORN B,SALA 202,Bom,\n'
        )
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(_make_csv([VALID_ROW, row2]), encoding="utf-8")

        db = DatabaseManager(db_path=tmp_path / "test.db")
        load_data_from_file(db.cursor, db.conn, str(csv_path))

        salas = db.get_all_salas()
        assert len(salas) == 2
        db.close()

    def test_maps_columns_by_name_and_ignores_extras(self, tmp_path):
        header = (
            "SALA,EXTRA,NUMERO,STATUS,ED,DESCRICAO,RÓTULOS,CARGA ATUAL,"
            "SETOR DO RESPONSÁVEL,CAMPUS DA CARGA,VALOR AQUISIÇÃO,VALOR DEPRECIADO,"
            "NUMERO NOTA FISCAL,NÚMERO DE SÉRIE,DATA DA ENTRADA,DATA DA CARGA,"
            "FORNECEDOR,ESTADO DE CONSERVAÇÃO,#\n"
        )
        row = (
            "LAB 3,ignorar,P777,Ativo,ED09,Armário,BLV-STI,Carga X,"
            "Setor Y,BLV,10.50,8.00,NF9,SER9,2024-01-01,2024-01-02,"
            "FORN Z,Regular,99\n"
        )
        csv_path = tmp_path / "reordered.csv"
        csv_path.write_text(header + row, encoding="utf-8")

        db = DatabaseManager(db_path=tmp_path / "test.db")
        load_data_from_file(db.cursor, db.conn, str(csv_path))

        salas = db.get_all_salas()
        assert [sala[1] for sala in salas] == ["LAB 3"]
        rows = db.get_patrimonios_by_sala(salas[0][0])
        assert rows[0][0] == "P777"
        assert rows[0][3] == "Armário"
        assert rows[0][4] == "BLV-STI"
        assert rows[0][7] == "blv"
        db.close()

    def test_dash_is_empty_and_total_row_is_skipped(self, tmp_path):
        row = (
            "1,P001,Ativo,ED01,Mesa,-,-,-,-,500.00,400.00,NF001,"
            "-,2020-01-01,2020-01-02,FORN A,-,Bom\n"
        )
        total = ",,,,,,,,,TOTAL,900.00,400.00,,,,,,\n"
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(_make_csv([row, total]), encoding="utf-8")

        db = DatabaseManager(db_path=tmp_path / "test.db")
        load_data_from_file(db.cursor, db.conn, str(csv_path))

        salas = db.get_all_salas()
        assert [sala[1] for sala in salas] == ["SEM SALA"]
        rows = db.get_patrimonios_by_sala(salas[0][0])
        assert len(rows) == 1
        assert rows[0][0] == "P001"
        assert rows[0][4] is None
        assert rows[0][8] is None
        db.close()

    def test_loads_xlsx(self, tmp_path):
        headers = [
            "#", "NUMERO", "STATUS", "ED", "DESCRICAO", "RÓTULOS",
            "CARGA ATUAL", "SETOR DO RESPONSÁVEL", "CAMPUS DA CARGA",
            "VALOR AQUISIÇÃO", "VALOR DEPRECIADO", "NUMERO NOTA FISCAL",
            "NÚMERO DE SÉRIE", "DATA DA ENTRADA", "DATA DA CARGA",
            "FORNECEDOR", "SALA", "ESTADO DE CONSERVAÇÃO",
        ]
        row = [
            "1", "P001", "Ativo", "ED01", "Mesa", "BLV-BIB",
            "Carga", "Setor", "BLV", "500.00", "400.00", "NF001",
            "SN001", "12/04/2010", "12/04/2010", "FORN A",
            "Biblioteca(BLOCO G: Administrativo)", "Bom",
        ]
        xlsx_path = tmp_path / "data.xlsx"
        _make_xlsx(xlsx_path, headers, [row])

        db = DatabaseManager(db_path=tmp_path / "test.db")
        load_data_from_file(db.cursor, db.conn, str(xlsx_path))

        salas = db.get_all_salas()
        assert salas[0][1] == "BIBLIOTECA(BLOCO G: ADMINISTRATIVO)"
        rows = db.get_patrimonios_by_sala(salas[0][0])
        assert rows[0][0] == "P001"
        assert rows[0][3] == "Mesa"
        assert rows[0][4] == "BLV-BIB"
        assert rows[0][9] == "Bom"
        db.close()

    def test_xlsx_decodes_excel_line_breaks(self, tmp_path):
        headers = [
            "#", "NUMERO", "STATUS", "ED", "DESCRICAO", "RÓTULOS",
            "CARGA ATUAL", "SETOR DO RESPONSÁVEL", "CAMPUS DA CARGA",
            "VALOR AQUISIÇÃO", "VALOR DEPRECIADO", "NUMERO NOTA FISCAL",
            "NÚMERO DE SÉRIE", "DATA DA ENTRADA", "DATA DA CARGA",
            "FORNECEDOR", "SALA", "ESTADO DE CONSERVAÇÃO",
        ]
        row = [
            "1", "P010", "Ativo", "ED01", "LINHA_x000D_\nDOIS", "",
            "", "", "BLV", "10.00", "9.00", "",
            "", "", "", "", "SALA 1", "Bom",
        ]
        xlsx_path = tmp_path / "breaks.xlsx"
        _make_xlsx(xlsx_path, headers, [row])

        db = DatabaseManager(db_path=tmp_path / "test.db")
        load_data_from_file(db.cursor, db.conn, str(xlsx_path))
        salas = db.get_all_salas()
        rows = db.get_patrimonios_by_sala(salas[0][0])
        assert rows[0][3] == "LINHA\r\nDOIS"
        db.close()


def _make_xlsx(path: Path, headers: list[str], data_rows: list[list[str]]) -> None:
    strings: list[str] = []
    index: dict[str, int] = {}

    def sid(value: str) -> int:
        if value not in index:
            index[value] = len(strings)
            strings.append(value)
        return index[value]

    def col_name(column: int) -> str:
        name = ""
        number = column + 1
        while number:
            number, remainder = divmod(number - 1, 26)
            name = chr(65 + remainder) + name
        return name

    sheet_rows = []
    for row_number, values in enumerate([headers, *data_rows], start=1):
        cells = []
        for column, value in enumerate(values):
            ref = f"{col_name(column)}{row_number}"
            cells.append(f'<c r="{ref}" t="s"><v>{sid(value)}</v></c>')
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    shared_items = "".join(f"<si><t>{escape(value)}</t></si>" for value in strings)
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>"
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(strings)}" uniqueCount="{len(strings)}">{shared_items}</sst>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships '
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Relatorio" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships '
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
