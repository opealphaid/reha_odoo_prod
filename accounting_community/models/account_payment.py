from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    banking_required = fields.Boolean(
        string="Requires Banking Report",
        default=False,
        help="Mark to include this payment in the bancarización report.",
    )
    banking_date = fields.Date(
        string="Banking Date",
        required=True,
        default=fields.Date.context_today,
        help="Date used for the banking report (may differ from the accounting date).",
    )
    banking_transaction_ref = fields.Char(
        string="Banking Transaction Reference",
        help="Transaction or operation number issued by the bank.",
    )
    banking_operation_type = fields.Selection(
        selection=[('sale', 'Venta'), ('purchase', 'Compra')],
        string="Operation Type",
    )
    banking_sale_type = fields.Selection(
        selection=[
            ('1', 'Ventas no sujetas a IVA (Venta de Bienes Inmuebles)'),
            ('2', 'Ventas con Emisión de Facturas'),
            ('3', 'Ventas de bienes con pagos anticipados a la emisión'),
        ],
        string="Sale Transaction Type",
    )
    banking_purchase_type = fields.Selection(
        selection=[
            ('1', 'Compra con retenciones'),
            ('2', 'Compra de inmuebles'),
            ('3', 'Compras Regímenes Especiales'),
            ('4', 'Compras con Factura'),
            ('5', 'Compras de bienes con pagos anticipados a la emisión de la factura'),
        ],
        string="Purchase Transaction Type",
    )
    banking_payment_form = fields.Selection(
        selection=[('1', 'Pago único'), ('2', 'Pagos parciales')],
        string="Payment Form",
    )
    banking_nit_complement = fields.Char(string="NIT Complement")
    banking_support_doc_type = fields.Selection(
        selection=[
            ('1', 'Recibo'),
            ('2', 'Documento de venta'),
            ('3', 'Documento de despacho'),
            ('4', 'Registro contable'),
            ('5', 'Otro documento de respaldo'),
        ],
        string="Support Document Type",
    )
    banking_support_doc_number = fields.Char(string="Support Document Number")
    banking_contract_number = fields.Char(string="Contract / Agreement Number")
    banking_credit_account = fields.Char(
        string="Supplier Credit Account",
        help="Supplier/vendor bank account number that receives the payment.",
    )
    banking_credit_entity_nit = fields.Char(
        string="Credit Entity NIT",
        help="NIT of the financial institution that holds the supplier account.",
    )
