"""GraphQL queries and variable helpers for the Shopify Admin API."""

# (variable prefix, app_config namespace column, app_config key column)
PRODUCT_METAFIELDS: list[tuple[str, str, str]] = [
    ("genres", "shopify_genres_ns", "shopify_genres_key"),
    ("type", "shopify_type_ns", "shopify_type_key"),
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
  	media(first: 1) { nodes { id preview { image { url } } } }
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