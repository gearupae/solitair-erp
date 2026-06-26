"""Fixed JSON schemas and cacheable instruction blocks for vendor quote AI pipeline."""

# GPT mini reads quote text and/or attached page images.
QUOTE_EXTRACT_INSTRUCTIONS = """You are a procurement data extractor reading vendor quotation documents.
You may receive plain text and/or page images from a PDF or Excel export.
Extract ONLY facts present in the document. Do not guess missing numbers — use null.
Default currency AED unless the document states otherwise.
Fill every schema field; use empty string or empty array when not found.
line_items: one row per product/service with description, qty, unit, unit_price, line_total.
risk_clauses: penalties, liability caps, exclusions, late fees, cancellation terms.
favorable_terms: payment flexibility, warranty, delivery guarantees."""

QUOTE_COMPARE_INSTRUCTIONS = """You are a senior procurement analyst comparing vendor quotations for a UAE company.
You receive structured quote JSON per vendor (already read from attached files).
Tasks:
1) Pick lowest grand_total vendor (lowest_total_vendor / lowest_total_amount).
2) Build vendor_totals[] with is_lowest on the cheapest.
3) Align line_items across vendors into item_comparisons[]; mark is_lowest on cheapest unit/line price.
4) price_history_comparisons[]: compare quoted unit prices vs historical averages (trend: higher|lower|inline|unknown).
5) compliance_review: overall_risk low|medium|high; issues[] with severity low|medium|high; merge risk_clauses from extractions.
6) recommended_vendor + recommended_reason (price, terms, delivery, risk — be specific).
7) summary (2-3 sentences), recommendations[] (2-4 bullets), warnings[] for gaps or conflicts.
Use AED unless quotes specify another currency. Be concise."""

PROMPT_CACHE_KEY_EXTRACT = 'gearup-vendor-quote-extract-v2'
PROMPT_CACHE_KEY_COMPARE = 'gearup-vendor-quote-compare-v2'
QUOTE_EXTRACTION_SCHEMA = {
    'type': 'object',
    'properties': {
        'vendor_name': {'type': 'string'},
        'currency': {'type': 'string'},
        'line_items': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'description': {'type': 'string'},
                    'quantity': {'type': ['number', 'null']},
                    'unit': {'type': 'string'},
                    'unit_price': {'type': ['number', 'null']},
                    'line_total': {'type': ['number', 'null']},
                },
                'required': ['description'],
                'additionalProperties': False,
            },
        },
        'subtotal': {'type': ['number', 'null']},
        'vat_amount': {'type': ['number', 'null']},
        'grand_total': {'type': ['number', 'null']},
        'payment_terms': {'type': 'string'},
        'validity_date': {'type': 'string'},
        'delivery_terms': {'type': 'string'},
        'warranty': {'type': 'string'},
        'risk_clauses': {'type': 'array', 'items': {'type': 'string'}},
        'favorable_terms': {'type': 'array', 'items': {'type': 'string'}},
        'extraction_notes': {'type': 'string'},
    },
    'required': ['vendor_name', 'currency', 'line_items', 'grand_total'],
    'additionalProperties': False,
}

# GPT mini compares structured quotes from attached files.
QUOTE_COMPARISON_SCHEMA = {
    'type': 'object',
    'properties': {
        'recommended_vendor': {'type': 'string'},
        'recommended_reason': {'type': 'string'},
        'lowest_total_vendor': {'type': 'string'},
        'lowest_total_amount': {'type': ['number', 'null']},
        'currency': {'type': 'string'},
        'vendor_totals': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'vendor': {'type': 'string'},
                    'total': {'type': ['number', 'null']},
                    'attachment_id': {'type': ['integer', 'null']},
                    'source': {'type': 'string'},
                    'is_lowest': {'type': 'boolean'},
                },
                'required': ['vendor', 'total', 'is_lowest'],
                'additionalProperties': False,
            },
        },
        'item_comparisons': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'item_description': {'type': 'string'},
                    'quantity': {'type': ['number', 'null']},
                    'unit': {'type': 'string'},
                    'vendor_prices': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'vendor': {'type': 'string'},
                                'unit_price': {'type': ['number', 'null']},
                                'line_total': {'type': ['number', 'null']},
                                'is_lowest': {'type': 'boolean'},
                            },
                            'required': ['vendor'],
                            'additionalProperties': False,
                        },
                    },
                    'lowest_vendor': {'type': 'string'},
                },
                'required': ['item_description'],
                'additionalProperties': False,
            },
        },
        'price_history_comparisons': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'item_description': {'type': 'string'},
                    'quoted_vendors': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'vendor': {'type': 'string'},
                                'unit_price': {'type': ['number', 'null']},
                            },
                            'required': ['vendor'],
                            'additionalProperties': False,
                        },
                    },
                    'historical_avg': {'type': ['number', 'null']},
                    'historical_low': {'type': ['number', 'null']},
                    'historical_high': {'type': ['number', 'null']},
                    'trend': {'type': 'string'},
                    'comment': {'type': 'string'},
                },
                'required': ['item_description'],
                'additionalProperties': False,
            },
        },
        'compliance_review': {
            'type': 'object',
            'properties': {
                'overall_risk': {'type': 'string'},
                'issues': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'vendor': {'type': 'string'},
                            'severity': {'type': 'string'},
                            'topic': {'type': 'string'},
                            'detail': {'type': 'string'},
                        },
                        'required': ['vendor', 'topic'],
                        'additionalProperties': False,
                    },
                },
                'favorable_terms': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['overall_risk', 'issues', 'favorable_terms'],
            'additionalProperties': False,
        },
        'summary': {'type': 'string'},
        'recommendations': {'type': 'array', 'items': {'type': 'string'}},
        'warnings': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': [
        'recommended_vendor',
        'recommended_reason',
        'lowest_total_vendor',
        'currency',
        'vendor_totals',
        'item_comparisons',
        'compliance_review',
        'summary',
        'recommendations',
        'warnings',
    ],
    'additionalProperties': False,
}
