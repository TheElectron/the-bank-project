# The Bank Project

O projeto está baseado em 3 etapas.
- Extração, processamento, enriquecimento e armazenamento dos dados utilizados;
- Geração de um modelo de ML;
- Geração de um chat conversacional;

## Dados

O ponto de partida deste projeto é o [The Berka Dataset](https://www.kaggle.com/datasets/marceloventura/the-berka-dataset), este conjunto de dados reune informações financeiras de um banco tcheco para o ano de 1999.\
Temos disponíveis oito tabelas, cada uma delas com o seguinte _schema_ de dados:

- _account_ (4500 registros):
   - account_id: Chave de identificação da conta;
   - district_id Chave de identificação do distrito;
   - date: Data de criação da conta, no formato AAMMDD;
   - frequency: Frequência de emissão do extrato
   ```
   {
      "POPLATEK MESICNE": "Mensal",
      "POPLATEK TYDNE": "Semanal",
      "POPLATEK PO OBRATU": "Por transação"
   }
   ```
- _card_ (892 registros):
   - card_id: Chave de identificação do cartão;
   - disp_id: Chave de identificação do _disp_ (elemento que relaciona o cliente e suas contas);
   - issued: Data de emissão do cartão, no formato: AAMMDD
   - type: Tipo de cartão:
   ```
      'junior', 'classic' e 'gold'
   ```
- _clients_ (5369 registros):
   - client_id: Chave de identificação do cliente;
   - district_id: Chave de identificação do distrito;
   - birth_number Data de nascimento e sexo, nos formatos AAMMDD (para homens) e AAMM+50DD (para mulheres)
- _disp_ (5369 registros):
   - disp_id: Chave de identificação do _disp_ (elemento que relaciona o cliente e suas contas);
   - client_id: Identificador do cliente;
   - account_id: Identificador da conta;
   - type: Tipo de _disp_ 
   ```
      Nota: Somente o proprietário pode emitir ordens  ou realizar empréstimos.
   ```
- _district_ (77 registros):
   - A1: district_id;
   - A2: Nome do Distrito;
   - A3: Região;
   - A4: Nº de Habitantes;
   - A5: Nº de Municípios com menos de 499 habitantes;
   - A6: Nº de Municípios com 500 a 1999 habitantes;
   - A7: Nº de Municípios com 2000 a 9999 habitantes;
   - A8: Nº de Municípios com mais de 10000 habitantes;
   - A9: Nº de Cidades;
   - A10: Proporção de habitantes urbanos;
   - A11: Salário Médio;
   - A12: Taxa de desemprego em 1995;
   - A13: Taxa de desemprego em 1996;
   - A14: Nº de Empreendedores por 1000 habitantes;
   - A15: Nº de Crimes cometidos em 1995;
   - A16: Nº de Crimes cometidos em 1996;

- _loan_ (682 registros):
   - loan_id: Chave de identificação do empréstimo;
   - account_id: Chave de identificação da conta;
   - date: Data de concessão do empréstimo, no formato AAMMDD;
   - amount: Valor do empréstimo;
   - duration: Duração do empréstimo, em meses;
   - payments: Valor do pagamento mensal;
   - status: Situação de pagamento do empréstimo
   ```
   {
      "A": "Contrato encerrado, sem dívidas",
      "B": "Contrato encerrado, empréstimo não pago",
      "C": "Contrato em vigor, em dia",
      "D": "Contrato em vigor, cliente em débito"
   }
   ```
- _order_ (6471 registros):
   - order_id: Chave de identificação da ordem;
   - account_id: Chave de identificação da conta emissora;
   - bank_to: Código do banco destinatário, composto por duas letras;
   - account_to: Chave de identificação da conta destinatária;
   - amount: Valor debitado da conta;
   - k_symbol: Propósito do pagamento
   ```
   {
      "POJISTNE": "Pagamento de seguro",
      "SIPO": "Pagamento doméstico",
      "LEASING": "Pagamento de leasing",
      "UVER": "Pagamento de empréstimo"
   }
   ```
- _trans_ (1.056.320 registros):
   - trans_id: Chave de identificação da transação;
   - account_id: Chave de identificação da conta;
   - date: Data da transação, no formato AAMMDD;
   - type: Tipo de transação
   ```
   {
      "PRIJEM": "Crédito",
      "VYDAJ": "Débito",
      "VYBER": "Saque (variação legada de VYDAJ para um subconjunto de transações)"
   }
   ```
   - operation: Modo de realização da transação
   ```
   {
      "VYBER KARTOU": "Saque com cartão",
      "VKLAD": "Depósito em dinheiro",
      "PREVOD Z UCTU": "Transferência recebida (de outro banco)",
      "VYBER": "Saque em dinheiro",
      "PREVOD NA UCET": "Transferência enviada (para outro banco)"
   }
   ```
   - amount: Valor da transação;
   - balance: Saldo da conta após a transação;
   - k_symbol: Caracterização da transação
   ```
   {
      "POJISTNE": "Pagamento de seguro",
      "SLUZBY": "Tarifa de emissão de extrato",
      "UROK": "Juros",
      "SANKC. UROK": "Juros de penalidade por saldo negativo",
      "SIPO": "Pagamento doméstico",
      "DUCHOD": "Pensão",
      "UVER": "Pagamento de empréstimo"
   }
   ```
   - bank: Código do banco parceiro, composto por duas letras (aplicável apenas a transferências);
   - account: Chave de identificação da conta parceira (aplicável apenas a transferências);

### Diagrama Entidade-Relacionamento

```mermaid
erDiagram
    DISTRICT ||--o{ ACCOUNT : "possui"
    DISTRICT ||--o{ CLIENT : "reside em"
    ACCOUNT ||--o{ DISP : "vinculada a"
    CLIENT ||--o{ DISP : "vinculado a"
    DISP ||--o{ CARD : "emite"
    ACCOUNT ||--o{ ORDER : "emite"
    ACCOUNT ||--o{ TRANS : "registra"
    ACCOUNT ||--o| LOAN : "contrai"

    DISTRICT {
        int A1 PK
        string A2
        string A3
        int A4
        int A5
        int A6
        int A7
        int A8
        int A9
        float A10
        float A11
        float A12
        float A13
        int A14
        int A15
        int A16
    }
    ACCOUNT {
        int account_id PK
        int district_id FK
        date date
        string frequency
    }
    CLIENT {
        int client_id PK
        int district_id FK
        string birth_number
    }
    DISP {
        int disp_id PK
        int client_id FK
        int account_id FK
        string type
    }
    CARD {
        int card_id PK
        int disp_id FK
        date issued
        string type
    }
    ORDER {
        int order_id PK
        int account_id FK
        string bank_to
        string account_to
        float amount
        string k_symbol
    }
    TRANS {
        int trans_id PK
        int account_id FK
        date date
        string type
        string operation
        float amount
        float balance
        string k_symbol
        string bank
        string account
    }
    LOAN {
        int loan_id PK
        int account_id FK
        date date
        float amount
        int duration
        float payments
        string status
    }
```

Para este projeto foi provisionado um datalake baseado na arquitetura Medallion, hospedado numa infraestrutura local. 
- Camada raw: contém os arquivos brutos no formato `.csv` do [The Berka Dataset](https://www.kaggle.com/datasets/marceloventura/the-berka-dataset). 
- Camada bronze: Cópia fiel dos arquivos originais, no formato `.parquet`.
- Camada silver: `real`, dados originais do conjunto devidamente tratados. O tratamento inclui a tipagem correta de cada coluna, o preenchimento dos valores nulos, datas parseadas e valores categóricos traduzidos para português.

### Estrutura gerada

```
datalake/
├── raw/                  # arquivos brutos, sem alterações
├── bronze/               # arquivos da camada raw no formato .parquet.
└── silver/
    └── real/              # dados devidamente tipados, nulos tratados, datas parseadas.
```

### Datalake Setup

```bash
# 1. Criação do ambiente virtual
python3 -m venv .datalake-venv
source .datalake-venv/bin/activate

# 2. Instação de dependências
pip install -r requirements.txt

# 3. Credenciais da Kaggle API 
##    Gere o token em https://www.kaggle.com/settings/api > Generate New Token
##    Alternativas também suportadas pelo script:
##      - variável de ambiente KAGGLE_API_TOKEN=<token>
##      - formato legacy ~/.kaggle/kaggle.json com {"username":..., "key":...}
mkdir -p ~/.kaggle
mv ~/Downloads/token ~/.kaggle/access_token   # Cole apenas o valor do token no arquivo
chmod 600 ~/.kaggle/access_token

# 4. Setup  inicial (Criação dos diretórios e dowload dos arquivos brutos)
python src/scripts/datalake_setup.py

# 5. Ingestão e processamento I (raw -> bronze)
python src/scripts/raw_to_bronze.py

# 6. Ingestão e processamento II (bronze -> silver/real)
python src/scripts/bronze_to_silver.py
```

## O que os scripts fazem

### `datalake_setup.py` (Raw)

1. Cria (de forma idempotente) as pastas da arquitetura Medallion.
2. Valida se as credenciais da Kaggle API estão configuradas.
3. Baixa o dataset `marceloventura/the-berka-dataset` (.zip).
4. Extrai o `.zip` em uma pasta temporária.
5. Move todos os `.csv` extraídos para `datalake/raw/`, sem alterar o
   conteúdo (via `shutil.move`).
6. Remove o `.zip` e a pasta temporária de extração.

### `raw_to_bronze.py` (Bronze)

1. Lê todos os `.csv` de `datalake/raw/` (delimitador `;`).
2. Converte cada um para `.parquet` (pandas + pyarrow) mantendo o mesmo
   nome (ex.: `client.csv` -> `client.parquet`).
3. Cópia 1:1: todas as colunas são lidas como `dtype=str`, sem inferência
   de tipo nem interpretação de valores nulos (`keep_default_na=False`),
   garantindo que a Bronze seja fiel byte-a-byte à Raw, só que em formato
   colunar.
4. Registra no log o número de linhas e colunas de cada arquivo
   convertido; falhas em um arquivo não interrompem os demais.

### `bronze_to_silver.py` (Silver/real)

1. Lê cada `.parquet` da Bronze (tudo `string`) e normaliza `""`, `" "` e
   `'?'` (marcador de nulo usado em `district.A12`/`A15`) para `NaN`.
2. Classifica colunas por nome/conteúdo: `id`, `*_id`, `*_to`, e
   `trans.account`/`district.A1` (overrides explícitos, pois não seguem a
   convenção de sufixo) permanecem `string`; `date` e `card.issued`
   (YYMMDD, também um override explícito) viram `datetime` (assume século
   19xx); demais colunas 100% numéricas viram `int` ou `float`; o restante
   permanece texto. O override de `district.A1` garante que a chave bata
   em tipo com as FKs `account.district_id`/`client.district_id` (ambas
   `string`), permitindo o join direto entre as tabelas.
3. Trata nulos: mediana para colunas numéricas, `'DESCONHECIDO'` para
   texto/categóricas (inclui as colunas de ID).
4. Regra específica da tabela `client`: decompõe `birth_number` em
   `gender` ('M'/'F') e `birth_date` (`datetime`), removendo a coluna
   original.
5. Traduz/adapta para português brasileiro os valores categóricos
   originalmente em tcheco (`CATEGORICAL_TRANSLATIONS`): ex.
   `account.frequency` (`POPLATEK MESICNE` -> `MENSAL`), `disp.type`
   (`OWNER` -> `TITULAR`), `trans.type` (`PRIJEM` -> `CREDITO`),
   `trans.operation`, `trans.k_symbol`/`order.k_symbol` e `loan.status`
   (códigos A-D adaptados para rótulos descritivos, ex. `ATIVO ADIMPLENTE`).
6. Grava o resultado em `datalake/silver/real/`, com logs detalhados por
   tabela (classificação de colunas, nulos preenchidos e valores
   traduzidos).

Todo o progresso é registrado via `logging` (nível INFO).
