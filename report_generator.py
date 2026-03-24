import os
import csv
import glob
import logging
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from database import get_data_dir

logger = logging.getLogger(__name__)


def _get_report_dir() -> Path:
    report_dir = get_data_dir() / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def _write_csv(path: Path, headers: list, rows: list) -> None:
    with open(path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    logger.info("CSV gerado: %s (%d linhas)", path, len(rows))


def _generate_report(db_manager) -> str:
    """Gera todos os CSVs de relatório. Retorna o caminho base como string."""
    base_dir = _get_report_dir()

    # Construir dicionário sala_id → nome uma única vez (elimina N+1)
    sala_id_to_nome: dict = {sid: sname for sid, sname in db_manager.get_all_salas()}

    geral_dir = base_dir / "_GERAL_"
    geral_dir.mkdir(exist_ok=True)

    # Coletar dados agrupados por sala
    salas: dict = {}
    geral_encontrados: list = []
    geral_nao_encontrados: list = []
    geral_divergentes: list = []

    for row in db_manager.get_relatorio_patrimonios():
        sala_id, sala_nome = row[0], row[1]
        if sala_id not in salas:
            salas[sala_id] = {
                "nome": sala_nome,
                "encontrados": [],
                "nao_encontrados": [],
                "divergentes": [],
            }
        if row[2] is not None:  # patrimônio pode ser None por causa do LEFT JOIN
            # row[2:] = (numero, status, ed, descricao, rotulos, carga_atual,
            #             setor_responsavel, campus_carga, numero_de_serie,
            #             estado_de_conservacao, encontrado, sala_id_original)
            pat = row[2:]
            encontrado = pat[-2]
            sala_id_original = pat[-1]
            is_divergent = sala_id_original is not None and sala_id_original != sala_id
            if encontrado == 1:
                salas[sala_id]["encontrados"].append(pat)
                geral_encontrados.append((sala_nome, pat))
            else:
                salas[sala_id]["nao_encontrados"].append(pat)
                geral_nao_encontrados.append((sala_nome, pat))
            if is_divergent:
                salas[sala_id]["divergentes"].append(pat)
                geral_divergentes.append((sala_nome, pat))

    # Patrimônios não cadastrados (escaneados mas não no banco)
    salas_unfound: dict = {}
    geral_unfound: list = []
    for sala_id, sala_nome, numero in db_manager.get_unfound_patrimonios():
        if sala_id not in salas_unfound:
            salas_unfound[sala_id] = {"unfound": []}
        salas_unfound[sala_id]["unfound"].append(numero)
        geral_unfound.append((sala_nome, numero))

    def pat_row(pat, lido_text: str) -> list:
        """Converte tupla de patrimônio em lista CSV-pronta."""
        row = list(pat)
        row[-2] = lido_text
        row[-1] = sala_id_to_nome.get(row[-1], "")
        return [str(v or "") for v in row]

    headers_sala = [
        "Número", "Status", "ED", "Descrição", "Rótulos", "Carga Atual",
        "Setor Responsável", "Campus Carga", "Número de Série",
        "Estado Conservação", "Encontrado", "Sala Original",
    ]
    headers_geral = ["Sala Atual"] + headers_sala

    # Limpar CSVs anteriores do diretório _GERAL_
    for f in glob.glob(str(geral_dir / "*.csv")):
        try:
            os.remove(f)
        except Exception as e:
            logger.warning("Erro ao remover %s: %s", f, e)

    _write_csv(
        geral_dir / "encontrados.csv", headers_geral,
        [[sala_nome] + pat_row(pat, "Lido") for sala_nome, pat in geral_encontrados],
    )
    _write_csv(
        geral_dir / "nao_encontrados.csv", headers_geral,
        [[sala_nome] + pat_row(pat, "Não Lido") for sala_nome, pat in geral_nao_encontrados],
    )
    _write_csv(
        geral_dir / "divergente.csv", headers_geral,
        [
            [sala_nome] + pat_row(pat, "Lido" if pat[-2] == 1 else "Não Lido")
            for sala_nome, pat in geral_divergentes
        ],
    )
    _write_csv(
        geral_dir / "nao_cadastrados.csv",
        ["Sala Atual", "Número"],
        [[sala_nome, numero] for sala_nome, numero in geral_unfound],
    )

    # CSVs por sala
    for sala_id, sala_info in salas.items():
        sala_nome = sala_info["nome"]
        safe_nome = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in sala_nome)
        sala_dir = base_dir / safe_nome
        try:
            sala_dir.mkdir(exist_ok=True)
        except Exception as e:
            logger.error("Erro ao criar diretório %s: %s", sala_dir, e)
            continue

        for f in glob.glob(str(sala_dir / "*.csv")):
            try:
                os.remove(f)
            except Exception as e:
                logger.warning("Erro ao remover %s: %s", f, e)

        _write_csv(
            sala_dir / "encontrados.csv", headers_sala,
            [pat_row(pat, "Lido") for pat in sala_info["encontrados"]],
        )
        _write_csv(
            sala_dir / "nao_encontrados.csv", headers_sala,
            [pat_row(pat, "Não Lido") for pat in sala_info["nao_encontrados"]],
        )
        _write_csv(
            sala_dir / "divergente.csv", headers_sala,
            [
                pat_row(pat, "Lido" if pat[-2] == 1 else "Não Lido")
                for pat in sala_info["divergentes"]
            ],
        )

        if sala_id in salas_unfound:
            _write_csv(
                sala_dir / "nao_cadastrados.csv",
                ["Número"],
                [[n] for n in salas_unfound[sala_id]["unfound"]],
            )

    logger.info("Relatório completo gerado em %s", base_dir)
    return str(base_dir)


class ReportWorker(QThread):
    """Worker para geração de relatório em thread separada, sem travar a UI."""

    finished = pyqtSignal(str)   # emite o path base do relatório
    error = pyqtSignal(str)      # emite a mensagem de erro

    def __init__(self, db_manager):
        super().__init__()
        self._db_manager = db_manager

    def run(self):
        try:
            base_dir = _generate_report(self._db_manager)
            self.finished.emit(base_dir)
        except Exception as e:
            logger.error("Erro ao gerar relatório: %s", e)
            self.error.emit(str(e))


class ReportGenerator:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def get_report_dir(self) -> Path:
        return _get_report_dir()

    def generate_report(self) -> str:
        """Gera relatórios de forma síncrona (uso em CLI). Retorna o caminho base."""
        return _generate_report(self.db_manager)

    def create_worker(self) -> ReportWorker:
        """Cria um ReportWorker para geração assíncrona na UI."""
        return ReportWorker(self.db_manager)
