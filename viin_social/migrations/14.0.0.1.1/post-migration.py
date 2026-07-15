from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    articles = env['social.article'].search([])
    articles._update_attachment()
