from .utils import identity as _


def get_custom_fields():
	return {
		"Purchase Invoice": [
			{
				"fieldname": "e_invoice_import",
				"label": _("E Invoice Import"),
				"insert_after": "bill_no",
				"fieldtype": "Link",
				"options": "E Invoice Import",
				"read_only": 1,
			}
		],
		"Customer": [
			{
				"fieldname": "buyer_reference",
				"label": _("Buyer Reference"),
				"insert_after": "language",
				"fieldtype": "Data",
			},
		],
		"Sales Order": [
			{
				"fieldname": "buyer_reference",
				"label": _("Buyer Reference"),
				"insert_after": "tax_id",
				"fieldtype": "Data",
				"fetch_from": "customer.buyer_reference",
				"fetch_if_empty": 1,
			},
		],
		"Sales Invoice": [
			{
				"fieldname": "buyer_reference",
				"label": _("Buyer Reference"),
				"insert_after": "tax_id",
				"fieldtype": "Data",
				"fetch_from": "customer.buyer_reference",
				"fetch_if_empty": 1,
			},
		],
	}
