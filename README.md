# suapcp

Aplicação desktop standalone para conferência de patrimônio do setor público, utilizando leitura de código de barras e dados CSV exportados pelo SUAP.

## Destaques

- Carrega arquivos CSV de inventário exportados pelo SUAP diretamente em um banco SQLite local
- Escaneia códigos de barras em tempo real com uma pistola sem fio para marcar itens como encontrados ou não cadastrados
- Filtra salas e patrimônios por nome; alterna a visualização por status (todos, encontrados, não encontrados)
- Gera relatórios CSV detalhados por sala e geral, incluindo itens encontrados, não encontrados, divergentes e não cadastrados
- Executa em Windows e Linux sem servidor ou conexão de rede

## Pré-requisitos

- **Python 3.7+** — [download](https://www.python.org/downloads/)
- **PyQt5** — instalado automaticamente via `make setup`

## Instalação

```bash
git clone https://github.com/carlosrabelo/suap-cp.git
cd suap-cp
make setup
```

## Uso

### Executar a aplicação

```bash
make run
```

### Carregar um CSV exportado do SUAP

```bash
.venv/bin/python app.py -load caminho/para/exportacao.csv
```

Isso importa os dados para o banco local e encerra. Inicie sem `-load` para uso interativo.

### Escanear e gerar relatório

1. Selecione uma sala na janela principal
2. Clique em **Escanear Patrimônios** e use a pistola para escanear itens
3. Clique em **Gerar Relatório** para exportar arquivos CSV para o diretório de relatórios

## Estrutura do Projeto

```
app.py              # Ponto de entrada — inicializa a interface e trata argumentos CLI
main_window.py      # Janela principal com tabelas de salas e patrimônios
scan_window.py      # Janela de escaneamento de código de barras
database.py         # Gerenciador SQLite e lógica de importação CSV
report_generator.py # Geração de relatórios CSV
requirements.txt    # Dependências Python
```

## Desenvolvimento

```bash
make setup      # Cria .venv e instala dependências (somente na primeira vez)
make run        # Executa a aplicação
make quality    # Formata, faz lint e verifica tipos
```

## Contribuição

1. Faça um fork do repositório
2. Crie uma branch para sua feature: `git checkout -b feat/descricao`
3. Faça commit com Conventional Commits: `git commit -m "feat: adiciona X"`
4. Faça push e abra um pull request

Desenvolvido no Instituto Federal de Educação, Ciência e Tecnologia de Mato Grosso (IFMT), Campus Cuiabá – Bela Vista, como parte de um projeto de estágio supervisionado.

## Licença

Este projeto é licenciado sob a MIT License — veja [LICENSE](LICENSE) para mais detalhes.
