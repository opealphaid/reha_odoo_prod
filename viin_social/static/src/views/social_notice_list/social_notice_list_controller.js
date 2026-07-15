/** @odoo-module */

import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list/list_controller";

export class SocialNoticeListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
    }

    async readAllNotices() {
        this.orm.call("social.notice", "action_read_all_notices", []).then(function () {
            location.reload();
        });
    }
}
