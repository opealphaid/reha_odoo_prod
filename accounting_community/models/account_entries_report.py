from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class AccountMoveReport(models.Model):
    _inherit = "account.move"

    page_break = fields.Boolean(string='Page Break', default=False)

    def getEntryItemsData(self):
        return self.line_ids

    def break_page(self):
        self.page_break = len(self.getEntryItemsData()) >= 12

    def get_account_lines_grouped(self):
        """Líneas agrupadas por cuenta filtrando por create_date del asiento."""
        company_id = self.env.company.root_id.id
        qry = """
            SELECT
                COALESCE(aa.code_store->>%s,
                         (SELECT value FROM jsonb_each_text(aa.code_store) LIMIT 1)) AS code,
                COALESCE(aa.name->>'es_BO', aa.name->>'en_US',
                         (SELECT value FROM jsonb_each_text(aa.name) LIMIT 1)) AS name,
                round(sum(aml.debit), 2) AS debito,
                round(sum(aml.credit), 2) AS credito,
                round(sum(aml.debit / 6.96), 2) AS debitosus,
                round(sum(aml.credit / 6.96), 2) AS creditosus
            FROM account_move_line AS aml
            LEFT JOIN account_account AS aa ON aa.id = aml.account_id
            WHERE aml.move_name IN (
                SELECT name FROM account_move WHERE create_date = %s
            )
            GROUP BY aa.name, aa.code_store
            ORDER BY debito DESC
        """
        self._cr.execute(qry, (str(company_id), str(self.create_date)))
        return self._cr.dictfetchall()

    def get_account_totals_grouped(self):
        """Totales filtrando por create_date del asiento."""
        qry = """
            SELECT
                round(sum(debit), 2) AS debito,
                round(sum(credit), 2) AS credito,
                round(sum(debit / 6.96), 2) AS debitosus,
                round(sum(credit / 6.96), 2) AS creditosus
            FROM account_move_line
            WHERE move_name IN (
                SELECT name FROM account_move WHERE create_date = %s
            )
        """
        self._cr.execute(qry, (str(self.create_date),))
        return self._cr.dictfetchall()

    def get_account_lines_individual(self):
        """Líneas agrupadas por cuenta filtrando por create_date de la línea."""
        company_id = self.env.company.root_id.id
        qry = """
            SELECT
                COALESCE(aa.code_store->>%s,
                         (SELECT value FROM jsonb_each_text(aa.code_store) LIMIT 1)) AS code,
                COALESCE(aa.name->>'es_BO', aa.name->>'en_US',
                         (SELECT value FROM jsonb_each_text(aa.name) LIMIT 1)) AS name,
                round(sum(aml.debit), 2) AS debito,
                round(sum(aml.credit), 2) AS credito,
                round(sum(aml.debit / 6.96), 2) AS debitosus,
                round(sum(aml.credit / 6.96), 2) AS creditosus
            FROM account_move_line AS aml
            LEFT JOIN account_account AS aa ON aa.id = aml.account_id
            WHERE aml.create_date = %s
            GROUP BY aa.name, aa.code_store
            ORDER BY debito DESC
        """
        self._cr.execute(qry, (str(company_id), str(self.create_date)))
        return self._cr.dictfetchall()

    def get_account_totals_individual(self):
        """Totales filtrando por create_date de la línea."""
        qry = """
            SELECT
                round(sum(debit), 2) AS debito,
                round(sum(credit), 2) AS credito,
                round(sum(debit / 6.96), 2) AS debitosus,
                round(sum(credit / 6.96), 2) AS creditosus
            FROM account_move_line
            WHERE create_date = %s
        """
        self._cr.execute(qry, (str(self.create_date),))
        return self._cr.dictfetchall()

    def run_sql2(self):
        qry = """
            SELECT create_date, string_agg(name, ', ' ORDER BY name) AS name
            FROM account_move
            WHERE create_date = %s
            GROUP BY create_date
            ORDER BY name ASC
        """
        self._cr.execute(qry, (str(self.create_date),))
        return self._cr.dictfetchall()

    def run_referenceStockMove(self):
        qry = """
            SELECT DISTINCT sm.reference AS ref
            FROM account_move AS am
            LEFT JOIN stock_move AS sm ON sm.id = stock_move_id
            WHERE am.create_date = %s
        """
        self._cr.execute(qry, (str(self.create_date),))
        return self._cr.dictfetchall()
