import json

from odoo import http
from odoo.http import content_disposition, request


class AccountingCommunityXlsxController(http.Controller):
    """Dedicated XLSX download route for accounting_community's own reports.

    Kept on its own path (instead of the generic /xlsx_report) because
    base_accounting_kit registers a controller on that same route with an
    incompatible signature, which breaks our reports as soon as that module
    is installed.
    """

    @http.route('/accounting_community/banking_xlsx_report', type='http',
                auth='user', methods=['POST'], csrf=False)
    def get_accounting_community_xlsx_report(self, report_name, data,
                                              context='{}', **kw):
        data = json.loads(data)
        context = json.loads(context or '{}')

        report = request.env['ir.actions.report'].sudo().search([
            ('report_name', '=', report_name),
            ('report_type', '=', 'xlsx'),
        ], limit=1)
        if not report:
            return request.not_found()

        try:
            docids = context.get('active_ids') or []
            content, _ext = report.with_context(**context)._render_xlsx(
                report.id, docids, data
            )
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'application/vnd.ms-excel'),
                    ('Content-Disposition',
                     content_disposition(f'{report.name}.xlsx')),
                ],
            )
        except Exception as e:
            se = http.serialize_exception(e)
            error = {
                'code': 200,
                'message': 'Odoo Server Error',
                'data': se,
            }
            return request.make_response(json.dumps(error))
