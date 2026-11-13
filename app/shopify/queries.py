"""GraphQL queries and variable helpers for the Shopify Admin API."""

import json


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
    ("release_date", "shopify_release_date_ns", "shopify_release_date_key"),
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
        id title price taxable inventoryQuantity barcode
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


M_PRODUCT_UPDATE: str = """
mutation ProductUpdate($product: ProductUpdateInput!) {
  productUpdate(product: $product) {
    product { id }
    userErrors { field message }
  }
}
"""

M_VARIANTS_UPDATE: str = """
mutation VariantsUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id }
    userErrors { field message }
  }
}
"""

M_VARIANTS_CREATE: str = """
mutation VariantsCreate($productId: ID!, $variants: [ProductVariantsBulkInput!]!,
                        $strategy: ProductVariantsBulkCreateStrategy!) {
  productVariantsBulkCreate(productId: $productId, variants: $variants,
                            strategy: $strategy) {
    productVariants { id inventoryItem { id } }
    userErrors { field message }
  }
}
"""

M_METAFIELDS_DELETE: str = """
mutation DelMf($metafields: [MetafieldIdentifierInput!]!) {
  metafieldsDelete(metafields: $metafields) { userErrors { field message } }
}
"""

M_VARIANT_MEDIA: str = """
mutation VariantMedia($productId: ID!, $variantMedia: [ProductVariantAppendMediaInput!]!) {
  productVariantAppendMedia(productId: $productId, variantMedia: $variantMedia) {
    userErrors { field message }
  }
}
"""

M_INVENTORY_SET: str = """
mutation SetQty($input: InventorySetQuantitiesInput!) {
  inventorySetQuantities(input: $input) { userErrors { field message } }
}
"""

Q_TAXONOMY: str = """
query($search: String!) {
  taxonomy { categories(first: 25, search: $search) { nodes { id name fullName } } }
}
"""

Q_PRODUCT_OPTIONS: str = "query($id: ID!) { product(id: $id) { options { id name } } }"

M_OPTION_UPDATE: str = """
mutation OptionUpdate($productId: ID!, $option: OptionUpdateInput!) {
  productOptionUpdate(productId: $productId, option: $option) {
    userErrors { field message }
  }
}
"""

M_PRODUCT_CREATE: str = """
mutation ProductCreate($product: ProductCreateInput!) {
  productCreate(product: $product) {
    product { id }
    userErrors { field message }
  }
}
"""

M_PRODUCT_DELETE: str = """
mutation ProductDelete($input: ProductDeleteInput!) {
  productDelete(input: $input) {
    deletedProductId
    userErrors { field message }
  }
}
"""

M_VARIANTS_DELETE: str = """
mutation VariantsDelete($productId: ID!, $variantsIds: [ID!]!) {
  productVariantsBulkDelete(productId: $productId, variantsIds: $variantsIds) {
    userErrors { field message }
  }
}
"""

Q_PUBLICATIONS: str = "query { publications(first: 20) { nodes { id app { title } } } }"

Q_VARIANT_PUBS: str = """
query($id: ID!) {
  productVariant(id: $id) {
    resourcePublications(first: 20) { nodes { isPublished publication { id app { title } } } }
  }
}
"""

M_PUBLISH: str = """
mutation Pub($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) { userErrors { field message } }
}
"""

M_UNPUBLISH: str = """
mutation Unpub($id: ID!, $input: [PublicationInput!]!) {
  publishableUnpublish(id: $id, input: $input) { userErrors { field message } }
}
"""

M_MEDIA_CREATE: str = """
mutation MediaCreate($productId: ID!, $media: [CreateMediaInput!]!) {
  productCreateMedia(productId: $productId, media: $media) {
    media { id status }
    mediaUserErrors { field message }
  }
}
"""

Q_MEDIA_STATUS: str = """
query($id: ID!) { node(id: $id) { ... on MediaImage { id status } } }
"""