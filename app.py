import sys
import logging
import argparse
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from main_window import MainWindow
from database import DatabaseManager, load_data_from_file, get_data_dir


def setup_logging() -> None:
    """Configura logging com arquivo rotativo e saída no console."""
    log_file = get_data_dir() / "suapcp.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

class App(QApplication):
    def __init__(self, argv, db_manager):
        super().__init__(argv)
        self.db_manager = db_manager

    def notify(self, receiver, event):
        """Sobrescreve notify para capturar exceções e evitar travamentos."""
        try:
            return super().notify(receiver, event)
        except Exception as e:
            print(f"Erro no ciclo de eventos: {e}")
            return False

if __name__ == "__main__":
    setup_logging()

    # Processar argumentos da linha de comando
    parser = argparse.ArgumentParser(description="SUAP-CP - Conferência de Patrimônio")
    parser.add_argument("-load", type=str, help="Caminho do arquivo CSV para carregar dados")
    args = parser.parse_args()

    # Inicializar o gerenciador de banco de dados
    db_manager = DatabaseManager()

    if args.load:
        # Modo não gráfico: apenas carregar o CSV e sair
        load_data_from_file(db_manager.cursor, db_manager.conn, args.load)
        db_manager.close()
        sys.exit(0)

    # Modo gráfico: abrir a interface
    # Habilitar suporte a High DPI
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, False)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = App(sys.argv, db_manager)
    window = MainWindow(db_manager)
    
    # Ajustar tamanho da janela para a tela do cliente
    screen = app.primaryScreen()
    size = screen.size()
    window.resize(size)
    
    # Maximizar a janela
    window.showMaximized()
    
    try:
        sys.exit(app.exec_())
    except Exception as e:
        print(f"Erro ao executar a aplicação: {e}")
    finally:
        db_manager.close()  # Garantir que o banco seja fechado