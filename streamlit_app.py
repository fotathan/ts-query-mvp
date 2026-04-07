import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# -----------------------------
# MVP CONFIG
# -----------------------------
# Keep this first version narrow and explicit.
# The AI/LLM step can be added later. For now we support:
# - country -> nutsCodes
# - category -> cpvCodes
# - status -> status
# - type of document -> typeOfDocument
# - estimated price min/max -> estimatedPrice
# - free keywords -> title/description/fulltext block
# - exclusions -> NOT block

FIELD_CONFIG = {
    "title": {"type": "text", "query_field": "title"},
    "description": {"type": "text", "query_field": "description"},
    "fulltext": {"type": "text", "query_field": "fulltext"},
    "cpvCodes": {"type": "text_codes", "query_field": "cpvCodes"},
    "nutsCodes": {"type": "text_codes", "query_field": "nutsCodes"},
    "natureOfContract": {"type": "multi", "query_field": "natureOfContract"},
    "typeOfDocument": {"type": "multi", "query_field": "typeOfDocument"},
    "subTypeOfDocument": {"type": "multi", "query_field": "subTypeOfDocument"},
    "status": {"type": "multi", "query_field": "status"},
    "procedure": {"type": "multi", "query_field": "procedure"},    "authorityTypes": {"type": "multi", "query_field": "authorityTypes"},
    "frameworkAgreement": {"type": "multi", "query_field": "frameworkAgreement"},
    "divisionIntoLots": {"type": "boolean", "query_field": "divisionIntoLots"},
    "publicationDate": {"type": "date_range", "query_field": "publicationDate"},
    "deadlineDate": {"type": "date_range", "query_field": "deadlineDate"},
    "demandingDate": {"type": "date_range", "query_field": "demandingDate"},
    "estimatedPrice": {"type": "range_currency", "query_field": "estimatedPriceCurrency"},
    "contractPrice": {"type": "range_currency", "query_field": "contractPriceCurrency"},
    "contractorName": {"type": "text", "query_field": "contractorName"},
    "categories": {"type": "text", "query_field": "categories"},
    "unspscCodes": {"type": "text_codes", "query_field": "unspscCodes"},
    "tenderItemName": {"type": "text", "query_field": "tenderItemName"},
    "keywords": {"type": "main_text"},
    "excludeKeywords": {"type": "main_text"},
}

COUNTRY_TO_NUTS = {
    "greece": ["el*", "gr*"],
    "cyprus": ["cy*"],
    "germany": ["de*"],
    "austria": ["at*"],
    "switzerland": ["ch*"],
    "romania": ["ro*"],
    "spain": ["es*"],
    "croatia": ["hr*"],
    "slovenia": ["si*"],
    "hungary": ["hu*"],
    "poland": ["pl*"],
    "czech republic": ["cz*"],
    "czechia": ["cz*"],
    "slovakia": ["sk*"],
    "serbia": ["rs*"],
    "bosnia": ["ba*"],
    "bulgaria": ["bg*"],
}

CATEGORY_TO_CPV = {
    "medicines": ["336*"],
    "medicine": ["336*"],
    "pharmaceuticals": ["336*"],
    "pharmaceutical": ["336*"],
    "cars": ["341*"],
    "vehicles": ["34*"],
    "software": ["48*"],
    "construction": ["45*"],

    # NEW: building-related exclusions (important for your case)
    "buildings": ["4521*", "453*", "454*"],
    "building": ["4521*", "453*", "454*"],
    "building construction": ["4521*", "453*", "454*"],
}

STATUS_SYNONYMS = {
    "active": ["active", "open", "current"],
    "expired": ["expired", "archived"],
}

TYPE_SYNONYMS = {
    "tender": ["tender", "tenders"],
    "prior_information": ["prior information"],
    "consultation": ["consultation", "consultations"],
    "procurement_plan": ["procurement plan", "procurement plans"],
    "other_information": ["other information"],
    "result": ["result", "results"],
}

PROCEDURE_MAP = {
    "open procedure": "open_procedure",
    "restricted procedure": "restricted_procedure",
    "accelerated restricted procedure": "accelerated_restricted_procedure",
    "negotiated procedure": "negotiated_procedure",
    "accelerated negotiated procedure": "accelerated_negotiated_procedure",
    "competitive dialogue": "competitive_dialogue",
    "negotiated without a call for competition": "negotiated_without_a_call_for_competition",
    "award of contract without prior publication of a contract notice": "award_of_contract_without_prior_publication_of_a_contract_notice",
    "not applicable": "not_applicable",
    "not specified": "not_specified",
    "direct award": "direct_award",
    "competitive procedure with negotiation": "competitive_procedure_with_negotiation",
    "concession award procedure": "concession_award_procedure",
    "concession award without prior concession notice": "concession_award_without_prior_concession_notice",
    "innovation partnership": "innovation_partnership",
    "auction": "auction",
    "simplified procedure": "simplified_procedure",
}

AUTHORITY_TYPE_MAP = {
    "ministry": "ministry_or_any_other_national_or_federal_authority",
    "armed forces": "armed_forces",
    "regional or local authority": "regional_or_local_authority",
    "utilities": "utilities",
    "european institution": "european_institution_agency_or_international_organisation",
    "international organisation": "european_institution_agency_or_international_organisation",
    "body governed by public law": "body_governed_by_public_law",
    "national or federal agency": "national_or_federal_agency_office",
    "regional or local agency": "regional_or_local_agency_office",
    "government": "government",
    "not applicable": "not_applicable",
    "not specified": "not_specified",
}

DEFAULT_DOCUMENT_TYPES_FOR_TENDER_INTENT = [
    "tender",
    "prior_information",
    "other_information",
    "procurement_plan",
    "consultation",
]


@dataclass
class PriceFilter:
    amount_from: Optional[float] = None
    amount_to: Optional[float] = None
    currency: Optional[str] = None


@dataclass
class ParsedDefinition:
    # Note: divisionIntoLots follows TS behavior:
    # - if True -> include divisionIntoLots:(true)
    # - if False or None -> DO NOT include the field at all

    status: List[str] = field(default_factory=list)
    typeOfDocument: List[str] = field(default_factory=list)
    nutsCodes: List[str] = field(default_factory=list)
    cpvCodes: List[str] = field(default_factory=list)
    excludeCpvCodes: List[str] = field(default_factory=list)
    procedure: List[str] = field(default_factory=list)
    authorityTypes: List[str] = field(default_factory=list)
    frameworkAgreementAnyOrMissing: bool = False
    estimatedPrice: Optional[PriceFilter] = None
    keywords: List[str] = field(default_factory=list)
    excludeKeywords: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": self.status,
            "typeOfDocument": self.typeOfDocument,
            "nutsCodes": self.nutsCodes,
            "cpvCodes": self.cpvCodes,
            "procedure": self.procedure,
            "authorityTypes": self.authorityTypes,
            "frameworkAgreementAnyOrMissing": self.frameworkAgreementAnyOrMissing,
            "keywords": self.keywords,
            "excludeKeywords": self.excludeKeywords,
            "warnings": self.warnings,
            "assumptions": self.assumptions,
        }
        if self.estimatedPrice:
            result["estimatedPrice"] = {
                "from": self.estimatedPrice.amount_from,
                "to": self.estimatedPrice.amount_to,
                "currency": self.estimatedPrice.currency,
            }
        return result


# -----------------------------
# PARSER
# -----------------------------
def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def extract_price(text: str) -> Optional[PriceFilter]:
    patterns = [
        r"(?:above|over|more than|greater than)\s+(\d+[\d,\.]*)\s*(euro|euros|eur)?",
        r"(?:from)\s+(\d+[\d,\.]*)\s*(euro|euros|eur)?",
        r"(?:below|under|less than)\s+(\d+[\d,\.]*)\s*(euro|euros|eur)?",
        r"(?:between)\s+(\d+[\d,\.]*)\s*(?:and|to)\s+(\d+[\d,\.]*)\s*(euro|euros|eur)?",
    ]

    # between X and Y
    match = re.search(patterns[3], text)
    if match:
        amount_from = float(match.group(1).replace(",", ""))
        amount_to = float(match.group(2).replace(",", ""))
        currency = "EUR" if match.group(3) else None
        return PriceFilter(amount_from=amount_from, amount_to=amount_to, currency=currency)

    # above/from
    for idx in [0, 1]:
        match = re.search(patterns[idx], text)
        if match:
            amount_from = float(match.group(1).replace(",", ""))
            currency = "EUR" if match.group(2) else None
            return PriceFilter(amount_from=amount_from, currency=currency)

    # below/under
    match = re.search(patterns[2], text)
    if match:
        amount_to = float(match.group(1).replace(",", ""))
        currency = "EUR" if match.group(2) else None
        return PriceFilter(amount_to=amount_to, currency=currency)

    return None


def extract_country_nuts(text: str) -> List[str]:
    found: List[str] = []
    for country, codes in COUNTRY_TO_NUTS.items():
        if country in text:
            found.extend(codes)
    return list(dict.fromkeys(found))


def extract_category_cpv(text: str) -> List[str]:
    found: List[str] = []
    for label, codes in CATEGORY_TO_CPV.items():
        if label in text:
            found.extend(codes)
    return list(dict.fromkeys(found))


def extract_status(text: str) -> List[str]:
    result: List[str] = []
    for canonical, variants in STATUS_SYNONYMS.items():
        if any(v in text for v in variants):
            result.append(canonical)
    return result


def extract_doc_types(text: str) -> List[str]:
    result: List[str] = []
    for canonical, variants in TYPE_SYNONYMS.items():
        if any(v in text for v in variants):
            result.append(canonical)
    return result


def extract_procedures(text: str) -> List[str]:
    result: List[str] = []
    for label, backend_value in PROCEDURE_MAP.items():
        if label in text:
            result.append(backend_value)
    return list(dict.fromkeys(result))


def extract_authority_types(text: str) -> List[str]:
    result: List[str] = []
    for label, backend_value in AUTHORITY_TYPE_MAP.items():
        if label in text:
            result.append(backend_value)
    return list(dict.fromkeys(result))


def extract_exclusions(text: str) -> List[str]:
    results: List[str] = []
    # Very simple MVP rule: "not X" or "except X"
    for pattern in [r"not ([a-zA-Z0-9\-\s]+)", r"except ([a-zA-Z0-9\-\s]+)"]:
        for match in re.finditer(pattern, text):
            phrase = match.group(1).strip()
            phrase = re.split(r"\b(from|with|above|below|under|over|and)\b", phrase)[0].strip()
            if phrase:
                results.append(phrase)
    return results


def extract_exclude_cpv_codes(exclude_keywords: List[str]) -> List[str]:
    found: List[str] = []
    for phrase in exclude_keywords:
        phrase_norm = phrase.strip().lower()
        for label, codes in CATEGORY_TO_CPV.items():
            if phrase_norm == label or phrase_norm in label or label in phrase_norm:
                found.extend(codes)
    return list(dict.fromkeys(found))


def extract_keywords(text: str, parsed: ParsedDefinition) -> List[str]:
    scrubbed = text

    for country in COUNTRY_TO_NUTS:
        scrubbed = scrubbed.replace(country, "")
    for category in CATEGORY_TO_CPV:
        scrubbed = scrubbed.replace(category, "")
    for variants in STATUS_SYNONYMS.values():
        for v in variants:
            scrubbed = scrubbed.replace(v, "")
    for variants in TYPE_SYNONYMS.values():
        for v in variants:
            scrubbed = scrubbed.replace(v, "")

    scrubbed = re.sub(r"(?:above|over|more than|greater than|from|below|under|less than|between)\s+\d+[\d,\.]*\s*(euro|euros|eur)?", "", scrubbed)
    scrubbed = re.sub(r"\b(give me|show me|find me|all the|all|for|from|with|that are|which are|priced|price)\b", "", scrubbed)
    scrubbed = re.sub(r"\s+", " ", scrubbed).strip(" ,.")

    if not scrubbed:
        return []

    # Split lightly; later you can improve with phrases and operators.
    return [scrubbed] if scrubbed else []


def parse_human_definition(user_text: str) -> ParsedDefinition:
    text = normalize_text(user_text)
    parsed = ParsedDefinition()

    parsed.status = extract_status(text)
    parsed.typeOfDocument = extract_doc_types(text)
    parsed.nutsCodes = extract_country_nuts(text)
    parsed.cpvCodes = extract_category_cpv(text)
    parsed.estimatedPrice = extract_price(text)
    parsed.procedure = extract_procedures(text)
    parsed.authorityTypes = extract_authority_types(text)
    parsed.frameworkAgreementAnyOrMissing = any(
        phrase in text for phrase in ["framework agreement", "framework agreements"]
    )
    parsed.excludeKeywords = extract_exclusions(text)
    parsed.excludeCpvCodes = extract_exclude_cpv_codes(parsed.excludeKeywords)
    parsed.keywords = extract_keywords(text, parsed)

    if not parsed.typeOfDocument and ("tender" in text or "tenders" in text):
        parsed.typeOfDocument = DEFAULT_DOCUMENT_TYPES_FOR_TENDER_INTENT.copy()
        parsed.assumptions.append(
            "Mapped 'tenders' to the default tender-oriented document types used in your example output."
        )

    if parsed.estimatedPrice and not parsed.estimatedPrice.currency:
        parsed.estimatedPrice.currency = "EUR"
        parsed.assumptions.append("No currency was specified, so EUR was assumed.")

    if "greece" in text and not parsed.nutsCodes:
        parsed.warnings.append("Greece was mentioned but no NUTS code could be mapped.")

    if "medicine" in text or "medicines" in text:
        parsed.assumptions.append("Mapped medicines/pharmaceuticals to CPV 336*.")

    if parsed.estimatedPrice:
        parsed.assumptions.append(
            "Estimated price range is emitted as a currency-specific range field, e.g. estimatedPriceEur:[min TO max]."
        )

    return parsed


# -----------------------------
# QUERY BUILDER
# -----------------------------
def quote_if_needed(term: str) -> str:
    term = term.strip()
    if not term:
        return term
    if " " in term and not (term.startswith('"') and term.endswith('"')):
        return f'"{term}"'
    return term


def build_or_group(values: List[str], quote_values: bool = False) -> str:
    cleaned = []
    for v in values:
        value = quote_if_needed(v) if quote_values else v
        cleaned.append(value)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return " OR ".join(cleaned)


def build_main_text_block(keywords: List[str]) -> str:
    if not keywords:
        return ""

    terms = [quote_if_needed(k) for k in keywords if k.strip()]
    if not terms:
        return ""

    joined = " OR ".join(terms)
    return f'(title:({joined}) OR description:({joined}) OR fulltext:({joined}))'


def build_exclusion_block(exclude_keywords: List[str], exclude_cpv_codes: List[str]) -> str:
    blocks: List[str] = []

    # 1. CPV exclusions (preferred)
    if exclude_cpv_codes:
        cpv_joined = " OR ".join(exclude_cpv_codes)
        blocks.append(f'cpvCodes:({cpv_joined})')

    # 2. Remaining text exclusions
    remaining_keywords = []
    for k in exclude_keywords:
        phrase_norm = k.strip().lower()
        matched = any(
            phrase_norm == label or phrase_norm in label or label in phrase_norm
            for label in CATEGORY_TO_CPV
        )
        if not matched:
            remaining_keywords.append(k)

    if remaining_keywords:
        terms = [quote_if_needed(k) for k in remaining_keywords if k.strip()]
        if terms:
            joined = " OR ".join(terms)
            blocks.append(f'(title:({joined}) OR description:({joined}) OR fulltext:({joined}))')

    if not blocks:
        return ""

    if len(blocks) == 1:
        return blocks[0]

    return " OR ".join(f'({b})' for b in blocks)


def build_multi_choice(field_name: str, values: List[str]) -> str:
    if not values:
        return ""
    joined = build_or_group(values, quote_values=True)
    return f'{field_name}:({joined})'


def build_code_field(field_name: str, values: List[str]) -> str:
    if not values:
        return ""
    joined = build_or_group(values, quote_values=False)
    return f'{field_name}:({joined})'


def build_estimated_price_clause(price: Optional[PriceFilter]) -> str:
    if not price:
        return ""

    # Based on the real generated query example provided by the user.
    # Currency-specific range fields appear to use names like estimatedPriceEur.
    field_name = "estimatedPriceEur"
    if price.currency and price.currency.upper() != "EUR":
        field_name = f'estimatedPrice{price.currency.title()}'

    lower = "*" if price.amount_from is None else str(int(price.amount_from))
    upper = "*" if price.amount_to is None else str(int(price.amount_to))
    return f'{field_name}:[{lower} TO {upper}]'


def build_boolean_field(field_name: str, value: Optional[bool]) -> str:
    # TS behavior: only include when True, otherwise omit entirely
    if value is True:
        return f"{field_name}:(true)"
    return ""


def build_ts_query(parsed: ParsedDefinition) -> str:
    positive_blocks: List[str] = []

    main_text = build_main_text_block(parsed.keywords)
    if main_text:
        positive_blocks.append(main_text)

    status_block = build_multi_choice("status", parsed.status)
    if status_block:
        positive_blocks.append(status_block)

    type_block = build_multi_choice("typeOfDocument", parsed.typeOfDocument)
    if type_block:
        positive_blocks.append(type_block)

    nuts_block = build_code_field("nutsCodes", parsed.nutsCodes)
    if nuts_block:
        positive_blocks.append(nuts_block)

    cpv_block = build_code_field("cpvCodes", parsed.cpvCodes)
    if cpv_block:
        positive_blocks.append(cpv_block)

    procedure_block = build_multi_choice("procedure", parsed.procedure)
    if procedure_block:
        positive_blocks.append(procedure_block)

    authority_block = build_multi_choice("authorityTypes", parsed.authorityTypes)
    if authority_block:
        positive_blocks.append(authority_block)

    if parsed.frameworkAgreementAnyOrMissing:
        positive_blocks.append('(frameworkAgreement:(0 OR 1) OR (*:* NOT frameworkAgreement:[* TO *]))')

    # divisionIntoLots handling (only include if true)
    division_block = build_boolean_field("divisionIntoLots", getattr(parsed, "divisionIntoLots", None))
    if division_block:
        positive_blocks.append(division_block)

    price_block = build_estimated_price_clause(parsed.estimatedPrice)
    if price_block:
        positive_blocks.append(price_block)

    negative_block = build_exclusion_block(parsed.excludeKeywords, parsed.excludeCpvCodes)

    query = " AND ".join(f"({block})" for block in positive_blocks if block)

    if negative_block:
        query = f"{query} AND NOT ({negative_block})" if query else f"NOT ({negative_block})"

    return query or ""


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="TS Query MVP", layout="wide")
st.title("TS Search Query MVP")
st.caption("Human-readable tender request → structured filters → TS query draft")

example = "Give me all the active tenders from Greece for medicines with price above 10000 Euros"
user_text = st.text_area(
    "Describe the search you want",
    value=example,
    height=120,
)

col1, col2 = st.columns([1, 1])

with col1:
    if st.button("Parse and generate query", type="primary"):
        parsed = parse_human_definition(user_text)
        query = build_ts_query(parsed)

        st.subheader("Detected filters")
        st.json(parsed.to_dict())

        st.subheader("Generated TS query draft")
        st.code(query or "No query could be generated.", language="text")

        if parsed.assumptions:
            st.subheader("Assumptions")
            for item in parsed.assumptions:
                st.write(f"- {item}")

        if parsed.warnings:
            st.subheader("Warnings")
            for item in parsed.warnings:
                st.warning(item)

with col2:
    st.subheader("How to improve next")
    st.markdown(
        """
1. Replace the rule-based parser with an LLM extraction step that outputs JSON only.
2. Expand the mapping dictionaries using your real search filters sheet.
3. Add exact builders for currency/date fields after collecting a few UI-generated examples.
4. Support operators like AND / OR / NOT inside keyword requests.
5. Add a validation layer so only allowed field values are emitted.
6. Add a 'show structured query' mode like the TS UI.
7. Keep `dataSource` out of the natural-language MVP because it is portal/language specific.
        """
    )

st.divider()
st.markdown(
    """
### Notes
- This first version intentionally uses a **deterministic builder** for the final query.
- The estimated price syntax now follows the real example pattern, e.g. `estimatedPriceEur:[10000 TO 100000]`.
- The country/category dictionaries are starter examples only.
- Other exact field syntaxes like `(*:* NOT dataSource:("ted"))`, switch defaults, and nullable-field patterns can now be added the same way from real samples.
    """
)
