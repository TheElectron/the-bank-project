"""Checks de qualidade da Silver: chaves únicas e integridade referencial."""

import pandas as pd

PRIMARY_KEYS = {
    "district": "district_id",
    "client": "client_id",
    "account": "account_id",
    "order": "order_id",
    "trans": "trans_id",
}
# (tabela filha, coluna, tabela pai)
FOREIGN_KEYS = (
    ("account", "district_id", "district"),
    ("client", "district_id", "district"),
    ("client", "account_id", "account"),
    ("order", "account_id", "account"),
    ("trans", "account_id", "account"),
)


class DataQualityError(ValueError):
    """A Silver violou uma regra de qualidade; carrega todas as violações encontradas."""


def check_silver(silver: dict[str, pd.DataFrame]) -> None:
    """Valida a Silver inteira e levanta `DataQualityError` listando todas as violações.

    Regras: PKs únicas e não nulas; FKs presentes na tabela pai; toda conta com
    exatamente 1 titular; cartão só em titular (README, "Camada Silver").
    """
    errors: list[str] = []
    for table, pk in PRIMARY_KEYS.items():
        col = silver[table][pk]
        if col.isna().any() or col.duplicated().any():
            errors.append(f"{table}.{pk}: chave nula ou duplicada")
    for child, column, parent in FOREIGN_KEYS:
        orphans = ~silver[child][column].isin(silver[parent][PRIMARY_KEYS[parent]])
        if orphans.any():
            errors.append(f"{child}.{column}: {int(orphans.sum())} valor(es) sem correspondente em {parent}")
    client = silver["client"]
    owners = client.loc[client["relationship_type"] == "TITULAR"].groupby("account_id").size()
    accounts = silver["account"]["account_id"]
    bad = accounts[accounts.map(owners).fillna(0) != 1]
    if len(bad):
        errors.append(f"account: {len(bad)} conta(s) sem exatamente 1 TITULAR")
    if (client["card_id"].notna() & (client["relationship_type"] != "TITULAR")).any():
        errors.append("client: cartão associado a cliente que não é TITULAR")
    if errors:
        raise DataQualityError("Silver inválida:\n- " + "\n- ".join(errors))
