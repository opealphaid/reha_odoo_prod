/* @odoo-module */

import { MessagingMenu } from "@mail/core/web/messaging_menu";

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(MessagingMenu.prototype, {
    /**
     * @override
     */
    get tabs() {
        const items = super.tabs;
        const hasSocialChats = Object.values(this.store.Thread.records).some(
            ({ type }) => type === "social_chat"
        );
        if (hasSocialChats) {
            items.push({
                id: "social_chat",
                icon: "fa fa-comments",
                label: _t("Social chat"),
            });
        }
        return items;
    },
});
