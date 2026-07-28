/** @odoo-module */
import { registry } from "@web/core/registry";
import { download } from "@web/core/network/download";
import { user } from "@web/core/user";

// report_name values of the xlsx reports defined by this module (see
// reports/*_actions.xml). Kept in sync manually with those files.
const OWN_XLSX_REPORTS = [
    "accounting_community.report_bankbook_xlsx",
    "accounting_community.report_sales_banking_xlsx",
    "accounting_community.report_purchase_banking_xlsx",
    "accounting_community.report_sales_iva_xlsx",
    "accounting_community.report_purchase_iva_xlsx",
];

// Low sequence so this handler is evaluated before third-party modules
// (e.g. base_accounting_kit) that register a generic handler for every
// report_type "xlsx" action and would otherwise hijack our downloads on
// the shared /xlsx_report route.
registry.category("ir.actions.report handlers").add(
    "accounting_community_xlsx_handler",
    async (action, options, env) => {
        if (action.report_type !== "xlsx" ||
            !OWN_XLSX_REPORTS.includes(action.report_name)) {
            return false;
        }

        env.services.ui.block();
        try {
            await download({
                url: "/accounting_community/banking_xlsx_report",
                data: {
                    report_name: action.report_name,
                    data: JSON.stringify(action.data || {}),
                    context: JSON.stringify({
                        ...user.context,
                        ...(action.context || {}),
                    }),
                },
            });
        } finally {
            env.services.ui.unblock();
        }

        if (options.onClose) {
            options.onClose();
        }
        return true;
    },
    { sequence: 1 }
);
