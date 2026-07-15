/* @odoo-module */

import { Record } from "@mail/core/common/record";
import { MessagingMenu } from "@mail/core/public_web/messaging_menu";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { DiscussApp } from "@mail/core/public_web/discuss_app_model";

patch(DiscussApp, {
    new(data) {
        const res = super.new(data);
        res.WpChannels = {
            extraClass: "o-mail-DiscussSidebarCategory-tus-WpChannels",
            icon: "fa fa-whatsapp",
            id: "WpChannels",
            name: _t("WhatsApp Messages"),
            hideWhenEmpty: false,
            isOpen: false,
            canView: false,
            canAdd: true,
            addTitle: _t("Start a Whatsapp Conversion"),
            serverStateKey: "is_discuss_sidebar_category_whatsapp_open",
            addHotkey: "w",
        };
        return res;
    },

});

patch(DiscussApp.prototype, {

     setup(env) {
        super.setup(env);
        this.WpChannels = Record.one("DiscussAppCategory");
    },
    sortThreads(t1, t2) {
        if (this.id === "WpChannels") {
            return (
                compareDatetime(t2.lastInterestDateTime, t1.lastInterestDateTime) || t2.id - t1.id
            );
        }
        return super.sortThreads(t1, t2);
    },

});

//MOBILE VIEW WHATSAPP IN DISCUSS
patch(MessagingMenu.prototype, {
    /**
     * @override
     */
    get tabs() {
        const items = super.tabs;
        items.push({
            icon: "fa fa-whatsapp",
            id: "WpChannels",
            label: _t("Whatsapp"),
        });
        return items;
    },

});

