# The Bank Project

O projeto está baseado em 3 etapas.
- Extração, processamento, enriquecimento e armazenamento dos dados utilizados;
- Geração de um modelo de ML;
- Geração de um chat conversacional;

## Pipeline de dados

Kaggle → Raw → Bronze → Silver → Gold → Feast, orquestrado por uma DAG do Airflow (`data_pipeline`) que só chama o código do pacote `the_bank_project`. Cada etapa também roda sozinha, pelo Makefile:

| Comando          | Etapa                                                                 |
| ---------------- | --------------------------------------------------------------------- |
| `make ingest`    | Kaggle → Raw (`.csv`) → Bronze (`.parquet`, cópia 1:1)                |
| `make silver`    | Bronze → Silver (tipagem, nulos, traduções, 8 → 5 tabelas, checks)    |
| `make gold`      | Silver → Gold (`gold_account` e `gold_account_monthly_movements`)     |
| `make features`  | Feast: registra as views (`apply`) e carrega o online store (`materialize`)  |
| `make up`/`down` | Sobe/derruba o Airflow em Docker (UI em http://localhost:8080)        |
| `make check`     | Lint, type check e testes (o mesmo que o CI roda)                     |

As credenciais do Kaggle vão em `.env` (modelo em `.env.example`). Os dados ficam em `data/{raw,bronze,silver,gold}/`, fora do git. Todas as etapas são idempotentes: reexecutar sobrescreve o resultado sem duplicar nada. Treino, serving e monitoramento ainda não foram implementados; ver `ROADMAP.md`.

## Dados

### Camada Bronze
O ponto de partida deste projeto é o [The Berka Dataset](https://www.kaggle.com/datasets/marceloventura/the-berka-dataset), este conjunto de dados reune informações financeiras de um banco tcheco, com transações de 1993 a 1998 (dataset divulgado em 1999).\
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

#### Diagrama Entidade-Relacionamento (conjunto original)
O diagrama abaixo descreve o schema original do Berka Dataset (8 tabelas),
tal como chega na camada Raw/Bronze. A camada Silver reorganiza esse
schema — ver [Reorganização na Silver](#reorganização-na-silver)
mais abaixo.

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

### Camada Silver

O schema de origem tem 8 tabelas e uma hierarquia de 4 níveis
(`district → account/client → disp → card/loan/order/trans`). Para
simplificar os relacionamentos e reduzir os joins necessários nas etapas
seguintes (modelagem) — a Silver consolida `disp` + `card` dentro de
`client`, e `loan` dentro de `account`.
`district` permanece como tabela dimensão separada (só as colunas
A1..A16 foram renomeadas), pois um join simples já resolve a relação sem
introduzir ambiguidade.

Os três merges usados na consolidação são **1:1, sem perda de dado** —
validado contra os dados reais antes da implementação:
- todo `client` tem exatamente 1 `disp` (nenhum cliente em mais de uma
  conta, nenhuma conta com mais de 1 titular ou mais de 1 dependente, e
  nunca o mesmo `client_id` como titular e dependente da mesma conta);
- todo `card` pertence a um `disp` do tipo `TITULAR` único (nenhum
  dependente tem cartão, nenhum titular tem mais de 1 cartão);
- toda `account` tem no máximo 1 `loan`.

Como resultado, temos:
- _district_ (77 registros) — colunas A1..A16 renomeadas e tipadas (o `?` de `A12` e `A15` no distrito 69 vira nulo):
   - district_id (era A1), district_name (A2), region (A3), population (A4),
     municipalities_under_499 (A5), municipalities_500_1999 (A6),
     municipalities_2000_9999 (A7), municipalities_over_10000 (A8),
     cities (A9), urban_population_ratio (A10), average_salary (A11),
     unemployment_rate_1995 (A12), unemployment_rate_1996 (A13),
     entrepreneurs_per_1000 (A14), crimes_1995 (A15), crimes_1996 (A16);
- _client_ (5369 registros; consolida _client_ + _disp_ + _card_):
   - client_id: Chave de identificação do cliente;
   - account_id: Chave de identificação da conta (todo cliente pertence a exatamente 1 conta);
   - relationship_type: Papel do cliente na conta
   ```
   {
      "TITULAR": "Proprietário — único que pode emitir ordens ou contrair empréstimos",
      "DEPENDENTE": "Dependente"
   }
   ```
   - district_id: Chave de identificação do distrito de residência;
   - gender: Sexo do cliente ('M'/'F'), derivado de `birth_number`;
   - birth_date: Data de nascimento, derivada de `birth_number`;
   - card_id: Chave de identificação do cartão (nulo para os 4477 clientes sem cartão — só titular pode ter);
   - card_type: Tipo de cartão (nulo se sem cartão)
   ```
      'junior', 'classic' e 'gold'
   ```
   - card_issued: Data de emissão do cartão (nulo se sem cartão);
- _account_ (4500 registros; consolida _account_ + _loan_):
   - account_id: Chave de identificação da conta;
   - district_id: Chave de identificação do distrito da conta;
   - frequency: Frequência de emissão do extrato
   ```
   {
      "POPLATEK MESICNE": "Mensal",
      "POPLATEK TYDNE": "Semanal",
      "POPLATEK PO OBRATU": "Por transação"
   }
   ```
   - date: Data de criação da conta;
   - loan_id: Chave de identificação do empréstimo (nulo para as 3818 contas sem empréstimo);
   - loan_date: Data de concessão do empréstimo (nulo se sem empréstimo);
   - loan_amount: Valor do empréstimo (nulo se sem empréstimo);
   - loan_duration: Duração do empréstimo em meses (nulo se sem empréstimo);
   - loan_payments: Valor do pagamento mensal (nulo se sem empréstimo);
   - loan_status: Situação de pagamento do empréstimo (nulo se sem empréstimo)
   ```
   {
      "A": "Contrato encerrado, sem dívidas",
      "B": "Contrato encerrado, empréstimo não pago",
      "C": "Contrato em vigor, em dia",
      "D": "Contrato em vigor, cliente em débito"
   }
   ```
- _order_ e _trans_: mesmo schema de origem, só tipadas e com as categóricas traduzidas.

Tratamentos aplicados a todas as tabelas (`src/the_bank_project/silver/`):
- **Tipagem:** datas `AAMMDD` viram `datetime` (século XX), valores numéricos viram `Int64`/`Float64`, ids permanecem texto;
- **Nulos:** os placeholders `""`, `" "` e `"?"` viram nulo (ex.: `k_symbol` em branco, `A12`/`A15` do distrito 69);
- **Categóricas traduzidas:** `frequency` (`MENSAL`, `SEMANAL`, `POR_TRANSACAO`), `relationship_type`, `trans.type`
  (`CREDITO`, `DEBITO`, `SAQUE`), `operation` e `k_symbol` (ex.: `SEGURO`, `JUROS`, `PAGAMENTO_EMPRESTIMO`).
  Um código fora do mapa interrompe o job em vez de virar nulo. `loan_status` e `card_type` mantêm o código original;
- **Validação automática:** os merges 1:1 acima são verificados a cada execução (`validate="1:1"` do pandas e
  `check_silver`), junto com chaves primárias únicas, integridade referencial, 1 titular por conta e cartão só para
  titular. Se qualquer regra falhar, nada é gravado.

#### Diagrama Entidade-Relacionamento (conjunto reestruturado)

```mermaid
erDiagram
    DISTRICT ||--o{ ACCOUNT : "possui"
    DISTRICT ||--o{ CLIENT : "reside em"
    ACCOUNT ||--o{ CLIENT : "vinculada a"
    ACCOUNT ||--o{ ORDER : "emite"
    ACCOUNT ||--o{ TRANS : "registra"

    DISTRICT {
        string district_id PK
        string district_name
        string region
        int population
        int municipalities_under_499
        int municipalities_500_1999
        int municipalities_2000_9999
        int municipalities_over_10000
        int cities
        float urban_population_ratio
        int average_salary
        float unemployment_rate_1995
        float unemployment_rate_1996
        int entrepreneurs_per_1000
        int crimes_1995
        int crimes_1996
    }
    CLIENT {
        string client_id PK
        string account_id FK
        string relationship_type
        string district_id FK
        string gender
        date birth_date
        string card_id
        string card_type
        date card_issued
    }
    ACCOUNT {
        string account_id PK
        string district_id FK
        string frequency
        date date
        string loan_id
        date loan_date
        int loan_amount
        int loan_duration
        float loan_payments
        string loan_status
    }
    ORDER {
        string order_id PK
        string account_id FK
        string bank_to
        string account_to
        float amount
        string k_symbol
    }
    TRANS {
        string trans_id PK
        string account_id FK
        date date
        string type
        string operation
        float amount
        float balance
        string k_symbol
        string bank
        string account
    }
```
### Camada Gold

A camada Gold consolida os dados tratados na Silver em estruturas orientadas ao consumo analítico e à geração de features para modelos de aprendizado supervisionado. Os dados são organizados em duas tabelas com granularidades diferentes, ambas com **`account_id` como entidade**: uma visão cadastral da conta e uma visão temporal do seu comportamento financeiro.

**Por que a conta e não o cliente?** O Berka tem 5.369 clientes para 4.500 contas. Os 869 dependentes compartilham a conta do titular e, portanto, a mesma série de transações e o mesmo target. Usá-los como entidade duplicaria observações idênticas e enviesaria as métricas dos modelos. Os atributos do cliente que interessam (sexo e nascimento do titular, cartão) entram como atributos da conta.

A Gold não define os modelos de ML nem seus conjuntos de treinamento. Seu objetivo é disponibilizar dados confiáveis, reutilizáveis e temporalmente consistentes para que diferentes times possam construir suas próprias features, visões analíticas e modelos. O código está em `src/the_bank_project/gold/` (`make gold`) e as tabelas são gravadas em `data/gold/`.

#### `gold_account`

Uma linha por `account_id` (4.500 registros). Reúne a conta, o distrito da conta, o titular, o cartão e o empréstimo, quando existentes. `account_open_date` é o timestamp da tabela para o Feature Store.

| Campo                             | Fonte Silver                      | Tipo    | Descrição                                                                                             |
| --------------------------------- | --------------------------------- | ------- | ----------------------------------------------------------------------------------------------------- |
| `account_id`                      | `account.account_id`              | string  | Identificador único da conta. **PK**                                                                  |
| `account_open_date`               | `account.date`                    | date    | Data de criação da conta. **Timestamp do Feast.**                                                     |
| `account_frequency`               | `account.frequency`               | string  | Frequência de emissão do extrato: `MENSAL`, `SEMANAL` ou `POR_TRANSACAO`.                             |
| `district_id`                     | `account.district_id`             | string  | Distrito da conta.                                                                                    |
| `district_name`                   | `district.district_name`          | string  | Nome do distrito da conta.                                                                            |
| `district_region`                 | `district.region`                 | string  | Região do distrito.                                                                                   |
| `district_population`             | `district.population`             | int     | População do distrito.                                                                                |
| `district_urban_ratio`            | `district.urban_population_ratio` | float   | Proporção da população urbana do distrito.                                                            |
| `district_average_salary`         | `district.average_salary`         | int     | Salário médio do distrito.                                                                            |
| `district_unemployment_1995`      | `district.unemployment_rate_1995` | float   | Taxa de desemprego em 1995 (nula no distrito 69, sem dado na origem).                                 |
| `district_unemployment_1996`      | `district.unemployment_rate_1996` | float   | Taxa de desemprego em 1996.                                                                           |
| `district_entrepreneurs_per_1000` | `district.entrepreneurs_per_1000` | int     | Número de empreendedores por 1000 habitantes.                                                         |
| `district_crimes_1995`            | `district.crimes_1995`            | int     | Crimes registrados em 1995 (nulo no distrito 69).                                                     |
| `district_crimes_1996`            | `district.crimes_1996`            | int     | Crimes registrados em 1996.                                                                           |
| `owner_client_id`                 | `client.client_id`                | string  | Cliente titular da conta.                                                                             |
| `owner_gender`                    | `client.gender`                   | string  | Sexo do titular (`M`/`F`).                                                                            |
| `owner_birth_date`                | `client.birth_date`               | date    | Data de nascimento do titular.                                                                        |
| `owner_district_id`               | `client.district_id`              | string  | Distrito de residência do titular (difere do da conta em 409 contas).                                 |
| `dependent_count`                 | Derivado de `client`              | int     | Número de dependentes da conta (0 ou 1 no dataset).                                                   |
| `has_card`                        | Derivado de `client.card_id`      | boolean | Indica se a conta tem cartão (só o titular pode ter).                                                 |
| `card_type`                       | `client.card_type`                | string  | Tipo do cartão: `junior`, `classic` ou `gold`. Nulo sem cartão.                                       |
| `card_issued_date`                | `client.card_issued`              | date    | Data de emissão do cartão. Nulo sem cartão.                                                           |
| `has_loan`                        | Derivado de `account.loan_id`     | boolean | Indica se a conta tem empréstimo.                                                                     |
| `loan_date`                       | `account.loan_date`               | date    | Data de concessão do empréstimo.                                                                      |
| `loan_amount`                     | `account.loan_amount`             | float   | Valor concedido no empréstimo.                                                                        |
| `loan_duration`                   | `account.loan_duration`           | int     | Duração do empréstimo em meses.                                                                       |
| `loan_payments`                   | `account.loan_payments`           | float   | Valor da parcela mensal.                                                                              |
| `loan_payment_ratio`              | Derivado                          | float   | Relação entre a parcela mensal e o valor do empréstimo.                                               |
| `loan_status`                     | `account.loan_status`             | string  | Situação do empréstimo (`A`–`D`). Origem do label de inadimplência, **não é feature**.                |

> **Atenção ao usar os campos `card_*` e `loan_*`:** são atributos estáticos, medidos ao fim do período, e a tabela é datada pela abertura da conta. Um cartão ou empréstimo emitido depois do mês de referência de uma observação **não** estava disponível naquele momento; ao montar datasets de treino, só use esses campos quando `card_issued_date`/`loan_date` forem anteriores ao mês da observação.

#### `gold_account_monthly_movements`

Uma linha por `account_id` e `reference_month`, agregada de `trans` (1.056.320 transações → 185.326 registros mensais, cobrindo as 4.500 contas entre 1993-01 e 1998-12). Os indicadores cobrem volume, entradas, saídas, saldo, composição das operações e histórico.

- **`reference_month` é o último dia do mês** (ex.: `1995-03-31`), quando as features do mês ficam completas. É o `event_timestamp` no Feast: uma consulta point-in-time feita em `T` só enxerga meses já encerrados.
- **Meses sem movimento entram na série**, entre o primeiro e o último mês com transação de cada conta (269 meses, 0,15%), com fluxos e contagens 0 e saldo carregado do mês anterior. Sem isso, `LAG` e as médias móveis olhariam para meses distantes. Os valores mínimo/médio/máximo das transações ficam nulos nesses meses.
- **Entradas** são as transações do tipo `CREDITO`; **saídas** são `DEBITO` e `SAQUE` (o `VYBER` do tipo, variante legada de débito).
- **`opening_balance` é uma estimativa.** O `balance` do Berka não fecha como razão contábil (`closing_balance ≠ opening_balance + net_flow` em cerca de 25% dos meses) e o `trans_id` não segue a ordem real dentro do mesmo dia. Por isso, o saldo de abertura/fechamento do dia é resolvido pela cadeia `balance − valor` das próprias transações do dia, e não pelo `trans_id`.
- Janelas (`*_3m_*`, `*_6m_*`) usam **só o mês de referência e os anteriores**; onde há menos meses que a janela, usam os disponíveis. Variações percentuais são nulas quando o mês anterior é 0 (indefinidas, não infinitas).
- `leasing_payment_amount`, previsto no desenho original, foi removido: `LEASING` só aparece em `order`, nunca em `trans`.

| Campo                          | Fonte                                   | Descrição                                                    |
| ------------------------------ | --------------------------------------- | ------------------------------------------------------------ |
| `account_id`                   | `trans.account_id`                      | Identificador da conta. **PK composta**                      |
| `reference_month`              | Derivado de `trans.date`                | Último dia do mês de referência. **PK composta, timestamp do Feast** |
| `account_age_months`           | Derivado                                | Idade da conta, em meses, no mês de referência.              |
| `year`                         | Derivado                                | Ano do mês de referência.                                    |
| `month`                        | Derivado                                | Mês do mês de referência.                                    |
| `transaction_count`            | `COUNT(trans_id)`                       | Número total de transações no mês.                           |
| `active_days`                  | `COUNT(DISTINCT date)`                  | Número de dias com movimentação.                             |
| `credit_transaction_count`     | `type = CREDITO`                        | Quantidade de transações de crédito.                         |
| `debit_transaction_count`      | `type IN (DEBITO, SAQUE)`               | Quantidade de transações de saída.                           |
| `withdrawal_transaction_count` | `operation IN (SAQUE_DINHEIRO, SAQUE_CARTAO)` | Quantidade de saques.                                  |
| `transfer_transaction_count`   | `operation IN (TRANSFERENCIA_*)`        | Quantidade de transferências (enviadas e recebidas).         |
| `inflow_amount`                | `type = CREDITO`                        | Total de recursos recebidos no mês.                          |
| `outflow_amount`               | `type IN (DEBITO, SAQUE)`               | Total de recursos debitados no mês.                          |
| `net_flow`                     | Derivado                                | Entradas menos saídas.                                       |
| `avg_transaction_amount`       | `amount`                                | Valor médio das transações.                                  |
| `min_transaction_amount`       | `amount`                                | Menor valor de transação.                                    |
| `max_transaction_amount`       | `amount`                                | Maior valor de transação.                                    |
| `opening_balance`              | Derivado de `balance`                   | Saldo estimado antes da primeira transação do mês.           |
| `closing_balance`              | Derivado de `balance`                   | Saldo após a última transação do mês.                        |
| `avg_balance`                  | `AVG(balance)`                          | Saldo médio observado nas transações do mês.                 |
| `min_balance`                  | `MIN(balance)`                          | Menor saldo observado no mês.                                |
| `max_balance`                  | `MAX(balance)`                          | Maior saldo observado no mês.                                |
| `cash_withdrawal_amount`       | `operation = SAQUE_DINHEIRO`            | Valor total de saques em dinheiro.                           |
| `card_withdrawal_amount`       | `operation = SAQUE_CARTAO`              | Valor total de saques com cartão.                            |
| `transfer_out_amount`          | `operation = TRANSFERENCIA_ENVIADA`     | Valor total de transferências enviadas.                      |
| `transfer_in_amount`           | `operation = TRANSFERENCIA_RECEBIDA`    | Valor total de transferências recebidas.                     |
| `loan_payment_amount`          | `k_symbol = PAGAMENTO_EMPRESTIMO`       | Valor total de pagamentos de empréstimos.                    |
| `insurance_payment_amount`     | `k_symbol = SEGURO`                     | Valor total de pagamentos de seguros.                        |
| `domestic_payment_amount`      | `k_symbol = PAGAMENTO_DOMESTICO`        | Valor total de pagamentos domésticos.                        |
| `interest_amount`              | `k_symbol = JUROS`                      | Valor associado a juros.                                     |
| `penalty_interest_amount`      | `k_symbol = JUROS_PENALIDADE`           | Valor associado a juros de penalidade.                       |
| `loan_payment_count`           | `k_symbol = PAGAMENTO_EMPRESTIMO`       | Quantidade de pagamentos de empréstimos.                     |
| `transfer_out_count`           | `operation`                             | Quantidade de transferências enviadas.                       |
| `transfer_in_count`            | `operation`                             | Quantidade de transferências recebidas.                      |
| `cash_withdrawal_count`        | `operation`                             | Quantidade de saques em dinheiro.                            |
| `card_withdrawal_count`        | `operation`                             | Quantidade de saques com cartão.                             |
| `previous_month_outflow`       | `LAG(outflow_amount)`                   | Total de saídas do mês anterior.                             |
| `previous_month_inflow`        | `LAG(inflow_amount)`                    | Total de entradas do mês anterior.                           |
| `outflow_3m_avg`               | Média móvel                             | Média das saídas dos últimos 3 meses (incluindo o atual).    |
| `outflow_3m_sum`               | Soma móvel                              | Soma das saídas dos últimos 3 meses.                         |
| `outflow_6m_avg`               | Média móvel                             | Média das saídas dos últimos 6 meses.                        |
| `inflow_3m_avg`                | Média móvel                             | Média das entradas dos últimos 3 meses.                      |
| `avg_balance_3m`               | Média móvel                             | Média do saldo médio dos últimos 3 meses.                    |
| `transaction_count_3m_avg`     | Média móvel                             | Média da quantidade de transações dos últimos 3 meses.       |
| `outflow_mom_change`           | Derivado                                | Variação percentual das saídas em relação ao mês anterior.   |
| `inflow_mom_change`            | Derivado                                | Variação percentual das entradas em relação ao mês anterior. |
| `balance_mom_change`           | Derivado                                | Variação absoluta do saldo de fechamento em relação ao mês anterior. |

#### Validações automáticas

`check_gold` roda a cada execução e, se qualquer regra falhar, nada é gravado:
- PK única em cada tabela e `gold_account` com exatamente as contas da Silver;
- sem nulos nos campos obrigatórios (chaves, datas, fluxos, saldos e janelas);
- toda conta da tabela mensal existe em `gold_account`;
- meses contíguos por conta e `reference_month` sempre no fim do mês;
- consistência das janelas: `outflow_3m_sum` não é menor que a saída do mês e `previous_month_outflow` bate com o mês anterior.

Os testes garantem ainda que alterar um mês futuro não muda nenhuma feature dos meses anteriores (anti-vazamento).

#### Diagrama Entidade-Relacionamento

```mermaid
erDiagram
    GOLD_ACCOUNT ||--o{ GOLD_ACCOUNT_MONTHLY_MOVEMENTS : "possui histórico mensal"

    GOLD_ACCOUNT {
        string account_id PK
        date account_open_date
        string account_frequency
        string district_id
        string district_name
        string district_region
        int district_population
        float district_urban_ratio
        int district_average_salary
        float district_unemployment_1995
        float district_unemployment_1996
        int district_entrepreneurs_per_1000
        int district_crimes_1995
        int district_crimes_1996
        string owner_client_id
        string owner_gender
        date owner_birth_date
        string owner_district_id
        int dependent_count
        boolean has_card
        string card_type
        date card_issued_date
        boolean has_loan
        date loan_date
        float loan_amount
        int loan_duration
        float loan_payments
        float loan_payment_ratio
        string loan_status
    }

    GOLD_ACCOUNT_MONTHLY_MOVEMENTS {
        string account_id PK
        date reference_month PK
        int account_age_months
        int year
        int month
        int transaction_count
        int active_days
        int credit_transaction_count
        int debit_transaction_count
        int withdrawal_transaction_count
        int transfer_transaction_count
        float inflow_amount
        float outflow_amount
        float net_flow
        float avg_transaction_amount
        float min_transaction_amount
        float max_transaction_amount
        float opening_balance
        float closing_balance
        float avg_balance
        float min_balance
        float max_balance
        float cash_withdrawal_amount
        float card_withdrawal_amount
        float transfer_out_amount
        float transfer_in_amount
        float loan_payment_amount
        float insurance_payment_amount
        float domestic_payment_amount
        float interest_amount
        float penalty_interest_amount
        int loan_payment_count
        int transfer_out_count
        int transfer_in_count
        int cash_withdrawal_count
        int card_withdrawal_count
        float previous_month_outflow
        float previous_month_inflow
        float outflow_3m_avg
        float outflow_3m_sum
        float outflow_6m_avg
        float inflow_3m_avg
        float avg_balance_3m
        float transaction_count_3m_avg
        float outflow_mom_change
        float inflow_mom_change
        float balance_mom_change
    }
```

## Feature Store (Feast)

A Gold é servida pelo Feast (`feature_repo/`), que é o **único ponto de acesso às features**: treino e serving passam por `the_bank_project.features`, e nenhum outro módulo lê a Gold diretamente.

- **Entidade:** `account` (chave `account_id`).
- **Offline store:** os parquets de `data/gold/` (usado no treino, com join *point-in-time*). **Online store:** SQLite local em `feature_repo/data/` (usado no serving), carregado com o valor mais recente de cada conta.
- **Views:** `account_static` (de `gold_account`, timestamp `account_open_date`) e `account_monthly` (de `gold_account_monthly_movements`, timestamp `reference_month`). O schema é explícito em `feature_repo/features.py` e um teste de contrato falha se ele divergir das colunas da Gold.
- **FeatureService `outflow_regression`:** as features da visão mensal e do histórico usadas pelo modelo de regressão (ver "Modelos Supervisionados"). O target não é uma feature.

```python
from the_bank_project.features import get_offline_features, get_online_features

# treino: uma linha por (conta, instante); volta o que era conhecido naquele instante
train = get_offline_features(entity_df)  # colunas: account_id, event_timestamp
# serving: o mês mais recente de cada conta
live = get_online_features(["1", "2"])
```

Pontos de atenção:
- **Point-in-time:** como `reference_month` é o fim do mês, uma consulta em `1995-03-30` enxerga fevereiro, não março (há teste para isso).
- **Sem TTL:** o offline store de arquivos do Feast descarta a linha inteira quando a feature expira, e quebra se todas expirarem. Por isso as views não têm TTL, e o dataset de treino deve partir de pares (conta, mês) reais da Gold, não de datas arbitrárias depois do último mês da conta. Linhas anteriores à abertura da conta não voltam do offline store.
- **Materialização completa:** `materialize_all` reprocessa o histórico inteiro (idempotente). A janela incremental do Feast é limitada pelo TTL a partir de "agora", e o dataset é de 1993–1998.
- **Versão do pandas:** o Feast exige `pandas<3`, então o projeto todo está em pandas 2.3 (dev, CI e a imagem do Airflow).

## Modelos Supervisionados

A partir da camada Gold serão construídos os datasets específicos para treinamento dos modelos. As tabelas Gold fornecem as variáveis observadas e derivadas, enquanto os **targets** são definidos de acordo com cada problema de negócio.

Essa separação permite reutilizar a mesma Gold em diferentes modelos e evita que variáveis que representam o futuro sejam disponibilizadas como features.

### Modelo de regressão | Gastos do próximo mês

O objetivo deste modelo é prever o valor total de saídas de uma conta no mês seguinte.

Matematicamente:

```text
X(T) → y(T+1)
```

Onde:

```text
X(T) = comportamento observado até o mês T
y(T+1) = outflow da conta no mês T+1
```

**Variável alvo:**

```text
next_month_outflow = outflow_amount(T+1)
```

A variável `next_month_outflow` não faz parte da Gold nem do conjunto de features disponibilizado no Feature Store. Ela é construída durante a preparação do dataset de treinamento, deslocando `outflow_amount` para o mês seguinte dentro de cada conta.

**Granularidade:**

```text
1 observação = 1 conta por mês
```

A Gold tem 185.326 registros mensais (1.056.320 transações agregadas por conta). O último mês de cada conta não tem mês seguinte e, portanto, não gera observação de treino; o número final de observações será definido na preparação do dataset.

**Modelos:**

```text
Regressão Linear (baseline)
        ↓
Random Forest Regressor
        ↓
Gradient Boosting
        ↓
XGBoost
```

A regressão linear será utilizada como baseline para estabelecer uma referência simples de desempenho. Os demais modelos serão avaliados para verificar se relações não lineares e interações entre as features contribuem para melhorar as previsões.

**Métricas observadas:**

```text
MAE
RMSE
R²
```

O MAE será utilizado para interpretar diretamente o erro médio de previsão, enquanto o RMSE dará maior peso a erros elevados e o R² permitirá avaliar a capacidade explicativa do modelo.

#### Features

**Visão mensal:**

```text
active_days
inflow_amount
outflow_amount
net_flow
transaction_count
avg_transaction_amount
max_transaction_amount
opening_balance
closing_balance
avg_balance
min_balance
max_balance
cash_withdrawal_amount
card_withdrawal_amount
transfer_out_amount
loan_payment_amount
insurance_payment_amount
domestic_payment_amount
```

**Histórico:**

```text
previous_month_outflow
previous_month_inflow
outflow_3m_avg
outflow_3m_sum
outflow_6m_avg
inflow_3m_avg
avg_balance_3m
transaction_count_3m_avg
outflow_mom_change
inflow_mom_change
balance_mom_change
```

Devido ao caráter temporal dos dados, o conjunto de treinamento não será dividido aleatoriamente. A divisão será realizada respeitando a ordem cronológica dos registros:

```text
Train      → 70% inicial do período
Validation → 20% seguinte
Test       → 10% final
```

Dessa forma, o modelo será treinado utilizando informações do passado e avaliado progressivamente em períodos posteriores, reduzindo o risco de *data leakage*.

---

### Modelo de classificação | Inadimplência

O objetivo deste modelo é prever se um empréstimo apresentará comportamento de inadimplência.
TBD