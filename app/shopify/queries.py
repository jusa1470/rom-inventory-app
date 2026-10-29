"""GraphQL queries and variable helpers for the Shopify Admin API."""

import json


PRODUCT_METAFIELDS: list[tuple[str, str, str]] = [
    ("genres", "shopify_genres_ns", "shopify_genres_key"),
    ("type", "shopify_type_ns", "shopify_type_key"),
    ("upc", "shopify_upc_ns", "shopify_upc_key"),
]

VARIANT_METAFIELDS: list[tuple[str, str, str]] = [
    ("upc", "shopify_upc_ns", "shopify_upc_key"),
    ("description", "shopify_description_ns", "shopify_description_key"),
    ("releaseDate", "shopify_release_date_ns", "shopify_release_date_key"),
    ("variantTags", "shopify_variant_tags_ns", "shopify_variant_tags_key"),
]

METAFIELDS: list[tuple[str, str, str]] = PRODUCT_METAFIELDS + VARIANT_METAFIELDS


def var_defs(entries: list[tuple[str, str, str]]) -> str:
    """GraphQL declarations for the metafield variables of the given entries."""
    defs: list[str] = []
    for prefix, _, _ in entries:
        defs.append(f"${prefix}Namespace: String!")
        defs.append(f"${prefix}Key: String!")
    return ", ".join(defs)


def vars_from_cfg(
    cfg: dict, entries: list[tuple[str, str, str]] = METAFIELDS
) -> dict[str, str]:
    """Metafield namespace/key variables from the app_config row."""
    variables: dict[str, str] = {}
    for prefix, ns_col, key_col in entries:
        for name, col in ((f"{prefix}Namespace", ns_col), (f"{prefix}Key", key_col)):
            if not cfg.get(col):
                raise ValueError(f"Missing value for {col}")
            variables[name] = cfg[col]
    return variables


VARIANT_FIELDS: str = """
fragment VariantFields on ProductVariant {
  	id title barcode sku price taxable inventoryQuantity
  	upc: metafield(namespace: $upcNamespace, key: $upcKey) { value }
  	description: metafield(namespace: $descriptionNamespace, key: $descriptionKey) { value }
  	release_date: metafield(namespace: $releaseDateNamespace, key: $releaseDateKey) { value }
  	variant_tags: metafield(namespace: $variantTagsNamespace, key: $variantTagsKey) { value }
  	media(first: 1) { nodes { id } }
  	inventoryItem {
		id
		unitCost { amount }
		measurement { weight { value unit } }
  	}
}
"""

Q_PRODUCTS: str = """
query GetProducts($first: Int!, $after: String, $query: String, $variantFirst: Int!, __VARS__) {
	products(first: $first, after: $after, query: $query) {
		pageInfo { hasNextPage endCursor }
		nodes {
			id title vendor status tags handle updatedAt productType
			category { id name }
			genres: metafield(namespace: $genresNamespace, key: $genresKey) { value }
			type: metafield(namespace: $typeNamespace, key: $typeKey) { value }
			upc: metafield(namespace: $upcNamespace, key: $upcKey) { value }
			media(first: 3) { nodes { id preview { image { url } } } }
			variants(first: $variantFirst) {
				pageInfo { hasNextPage endCursor }
				nodes { ...VariantFields }
			}
		}
	}
}
""".replace("__VARS__", var_defs(METAFIELDS)) + VARIANT_FIELDS

Q_MORE_VARIANTS: str = """
query MoreVariants($id: ID!, $after: String, $variantFirst: Int!, __VARS__) {
	product(id: $id) {
		variants(first: $variantFirst, after: $after) {
			pageInfo { hasNextPage endCursor }
			nodes { ...VariantFields }
		}
  	}
}
""".replace("__VARS__", var_defs(VARIANT_METAFIELDS)) + VARIANT_FIELDS

Q_LOCATIONS: str = "query { locations(first: 10) { nodes { id name isPrimary } } }"

Q_PRODUCTS_COUNT: str = (
    "query($query: String) { productsCount(query: $query, limit: null) { count } }"
)

M_BULK_RUN: str = """
mutation RunBulk($query: String!) {
  bulkOperationRunQuery(query: $query) {
    bulkOperation { id status }
    userErrors { field message }
  }
}
"""

M_BULK_CANCEL: str = """
mutation CancelBulk($id: ID!) {
  bulkOperationCancel(id: $id) { userErrors { field message } }
}
"""

Q_BULK_STATUS: str = """
query BulkStatus($id: ID!) {
  node(id: $id) {
    ... on BulkOperation { id status errorCode objectCount url }
  }
}
"""

# (alias, app_config namespace column, app_config key column)
BULK_PRODUCT_MF: list[tuple[str, str, str]] = [
    ("genres", "shopify_genres_ns", "shopify_genres_key"),
    ("type", "shopify_type_ns", "shopify_type_key"),
    ("upc", "shopify_upc_ns", "shopify_upc_key")
]
BULK_VARIANT_MF: list[tuple[str, str, str]] = [
    ("upc", "shopify_upc_ns", "shopify_upc_key"),
    ("description", "shopify_description_ns", "shopify_description_key"),
    ("release_date", "shopify_release_date_ns", "shopify_release_date_key"),
    ("variant_tags", "shopify_variant_tags_ns", "shopify_variant_tags_key"),
]


def bulk_products_query(cfg: dict, search: str | None = None) -> str:
    """Bulk-operation query: no variables or pagination args are allowed, so the
    metafield namespace/keys are inlined."""

    def mf(alias: str, ns_col: str, key_col: str) -> str:
        for col in (ns_col, key_col):
            if not cfg.get(col):
                raise ValueError(f"Missing value for {col}")
        return (
            f"{alias}: metafield(namespace: {json.dumps(cfg[ns_col])}, "
            f"key: {json.dumps(cfg[key_col])}) {{ value }}"
        )

    product_mf = " ".join(mf(*e) for e in BULK_PRODUCT_MF)
    variant_mf = " ".join(mf(*e) for e in BULK_VARIANT_MF)
    args = f"(query: {json.dumps(search)})" if search else ""
    return f"""{{
  products{args} {{
    edges {{ node {{
      id title vendor status tags handle updatedAt productType
      category {{ id name }}
      {product_mf}
      media {{ edges {{ node {{ id preview {{ image {{ url }} }} }} }} }}
      variants {{ edges {{ node {{
        id title barcode sku price taxable inventoryQuantity
        {variant_mf}
        media {{ edges {{ node {{ id }} }} }}
        inventoryItem {{
          id
          unitCost {{ amount }}
          measurement {{ weight {{ value unit }} }}
        }}
      }} }} }}
    }} }}
  }}
}}"""