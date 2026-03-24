# CLAUDE.md — Diretrizes do Projeto SUAP-CP

Projeto interno do **IFMT (Instituto Federal de Mato Grosso)**. Todo conteúdo voltado ao usuário e ao desenvolvedor deve ser em **português brasileiro**.

## Idioma

### Obrigatório em português
- `README.md` — documentação principal do projeto
- Docstrings de funções, métodos e classes
- Comentários inline no código-fonte Python
- Comentários dos targets e variáveis no `Makefile` (incluindo os textos após `##` usados pelo `help`)
- Mensagens de log (`logging.info`, `logging.error`, etc.)
- Strings de interface gráfica (labels, botões, títulos de janela, mensagens de feedback)
- Cabeçalhos de CSV e relatórios
- Nomes de colunas e tabelas do banco de dados
- Mensagens de erro exibidas ao usuário

### Pode permanecer em inglês
- Nomes de funções e métodos (convenção Python: `snake_case`)
- Nomes de variáveis genéricas (`event`, `index`, `value`, etc.)
- Nomes de classes (convenção Python: `PascalCase`)
- Identificadores técnicos de bibliotecas externas (PyQt5, SQLite, etc.)

### Termos de domínio
Identificadores de domínio do SUAP devem seguir a nomenclatura já estabelecida no projeto:
`patrimonio`, `sala`, `carga_atual`, `setor_responsavel`, `estado_de_conservacao`, etc.

## README.md

- Escrito integralmente em português
- Não há versão em inglês (projeto interno)
