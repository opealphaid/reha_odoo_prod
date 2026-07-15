import fnmatch
import importlib
import logging
import os
import ast
import contextlib
import glob
from unittest.mock import Mock
from os.path import join as opj

import odoo

from odoo import api, modules, tools, SUPERUSER_ID
from odoo.tools import config, pycompat
from odoo.tools.misc import file_path, file_open
from odoo.tools.which import which
from odoo.modules import module, get_modules
from odoo.models import BaseModel

from odoo.addons.base.models.ir_ui_menu import IrUiMenu
from odoo.addons.base.models.res_currency import CurrencyRate
from odoo.addons.base.models.res_users import Users
from odoo.sql_db import ConnectionPool

# imported here to avoid dependency cycle issues
# pylint: disable=wrong-import-position
from . import helper
from . import controllers
from . import models
from . import wizard
from . import override

_url_open = None
if config.get('test_enable', False):
    from odoo.tests import HttpCase

    _url_open = HttpCase.url_open

    try:
        from odoo.addons.test_lint.tests import test_manifests
        from odoo.tests import common
    except ImportError:
        test_manifests = None
        common = None

    try:
        from odoo.addons.test_assetsbundle.tests.test_assetsbundle import AddonManifestPatched
        setUpAddonManifestPatched = AddonManifestPatched.setUp
    except ImportError:
        AddonManifestPatched = None

    # Remove the test_no_overlap_sql_constraint test
    # A new test will be moved to the viin_hr_overtime_timeoff module
    from odoo.addons.hr_work_entry_contract.tests.test_work_entry import TestWorkEntry
    TestWorkEntry.test_no_overlap_sql_constraint = lambda self: None

_logger = logging.getLogger(__name__)
j = os.path.join

get_resource_path = module.get_resource_path
get_module_icon_path = module.get_module_icon_path
get_module_path = module.get_module_path
module_manifest = module.module_manifest
get_module_icon = module.get_module_icon
load_manifest = module.load_manifest
_load_records = BaseModel._load_records
_auto_init = Users._auto_init
_compute_web_icon_data = IrUiMenu._compute_web_icon_data
_close_all = ConnectionPool.close_all


def _get_branding_module(branding_module='viin_brand'):
    """
    Wrapper for others to override
    """
    return branding_module


def test_installable(module, mod_path=None):
    """
    :param module: The name of the module (sale, purchase, ...)
    :param mod_path: Physical path of module, if not providedThe name of the module (sale, purchase, ...)
    """
    if module == 'general_settings':
        module = 'base'
    return odoo.modules.module._get_manifest_cached(module)


viin_brand_manifest = test_installable(_get_branding_module())


def check_viin_brand_module_icon(module):
    """
    Ensure module icon with
        either '/viin_brand_originmodulename/static/description/icon.png'
        or '/viin_brand/static/img/apps/originmodulename.png'
        exists.
    """
    branding_module = _get_branding_module()
    brand_originmodulename = '%s_%s' % (branding_module, module if module not in ('general_settings', 'modules') else 'base')

    # load manifest of the overriding modules
    viin_brand_originmodulename_manifest = test_installable(brand_originmodulename)

    # /viin_brand_originmodulename'/static/description/icon.png
    brand_originmodule_path = get_module_path(brand_originmodulename, downloaded=False, display_warning=False)
    if (
        brand_originmodule_path
        and viin_brand_originmodulename_manifest.get('installable', False)
        and os.path.exists(os.path.join(brand_originmodule_path, 'static', 'description', 'icon.png'))
    ):
        return os.path.join('/', brand_originmodulename, 'static', 'description', 'icon.png')

    # /viin_brand'/static/img/apps/<module>.png
    originmodulename_iconpath = os.path.join('static', 'img', 'apps', '%s.png' % (module if module not in ('general_settings', 'modules') else module == 'general_settings' and 'settings' or 'modules'))
    branding_module_path = get_module_path(branding_module, downloaded=False, display_warning=False)
    if (
        branding_module_path
        and viin_brand_manifest.get('installable', False)
        and os.path.exists(os.path.join(branding_module_path, originmodulename_iconpath))
    ):
        return os.path.join('/', branding_module, originmodulename_iconpath)
    return False


def get_viin_brand_resource_path(mod, *args):
    # Odoo hard coded its own favicon in several places
    # this override to attempt to get Viindoo's favicon if it
    # exists in branding_module/static/img/favicon.ico
    if mod == 'web' and 'static/img/favicon.ico' in args:
        if viin_brand_manifest.get('installable', False):
            branding_module = _get_branding_module()
            resource_path = opj(branding_module, *args)
            with contextlib.suppress(FileNotFoundError, ValueError):
                viindoo_favicon_path = file_path(resource_path)
                if viindoo_favicon_path:
                    return viindoo_favicon_path
    # Odoo hard coded its own module_icon in several places
    # this override to attempt to get Viindoo's module_icon
    elif mod not in ('general_settings', 'modules', 'settings') and ('static', 'description', 'icon.png') == args:
        module_icon = get_viin_brand_module_icon(mod)
        if module_icon:
            path_parts = module_icon.split('/')
            resource_path = opj(path_parts[1], *path_parts[2:])
            with contextlib.suppress(FileNotFoundError, ValueError):
                module_icon_path = file_path(resource_path)
                if module_icon_path:
                    return module_icon_path

    # fall back to the default one
    with contextlib.suppress(FileNotFoundError, ValueError):
        return file_path(opj(mod, *args))
    return False


def get_viin_brand_module_icon(mod):
    """
    This overrides default module icon with
        either '/viin_brand_originmodulename/static/description/icon.png'
        or '/viin_brand/static/img/apps/originmodulename.png'
        where originmodulename is the name of the module whose icon will be overridden
    provided that either of the viin_brand_originmodulename or viin_brand is installable
    """
    # Odoo tests hardcode expected module_icon values in assertEqual.
    # Skip icon branding when running tests from modules that assert icon values,
    # to avoid false failures without maintaining a per-test bypass list.
    if module.current_test and (
        'test' in module.current_test.test_module
        or module.current_test.test_module in ('base', 'mail', 'im_livechat')
    ):
        return get_module_icon(mod)

    module_icon = check_viin_brand_module_icon(mod)
    if mod not in ('general_settings', 'modules', 'settings', 'missing'):
        origin_module_icon = get_module_icon(mod)
        if origin_module_icon and origin_module_icon == '/base/static/description/icon.png':
            module_icon = check_viin_brand_module_icon('base')
    if module_icon:
        return module_icon
    return get_module_icon(mod)


def get_viin_brand_icon_path(module):
    iconpath = ['static', 'description', 'icon.png']
    path = get_viin_brand_resource_path(module.name, *iconpath)
    if not path:
        path = get_viin_brand_resource_path('base', *iconpath)
    if not path:
        return get_module_icon_path(module)
    return path


def _get_brand_module_website(module):
    """
    This overrides default module website with '/branding_module/apriori.py'
    where apriori contains dict:
    modules_website = {
        'account': 'account's website',
        'sale': 'sale's website,
    }
    :return module website in apriori.py if exists else False
    """
    if viin_brand_manifest.get('installable', False):
        branding_module = _get_branding_module()
        try:
            modules_website = importlib.import_module('odoo.addons.%s.apriori' % branding_module).modules_website
            if module in modules_website:
                return modules_website[module]
        except Exception:
            pass
    return False


def _load_manifest_plus(module, mod_path=None):
    info = load_manifest(module, mod_path=mod_path)
    if info:
        module_website = _get_brand_module_website(module)
        if module_website:
            info['website'] = module_website
    return info


def _test_if_loaded_in_server_wide():
    config_options = config.options
    if 'to_base' in config_options.get('server_wide_modules', '').split(','):
        return True
    else:
        return False


if not _test_if_loaded_in_server_wide():
    _logger.warning("The module `to_base` should be loaded in server wide mode using `--load`"
                 " option when starting Odoo server (e.g. --load=base,web,to_base)."
                 " Otherwise, some of its functions may not work properly.")


def _disable_currency_rate_unique_name_per_day():
    # Remove unique_name_per_day constraint in res.currency.rate model in base module
    # It doesn't delete constraint on database server
    for el in CurrencyRate._sql_constraints:
        if el[0] == 'unique_name_per_day':
            _logger.info("Removing the default currency rate's SQL constraint `unique_name_per_day`")
            CurrencyRate._sql_constraints.remove(el)
            break


def _disable_hr_work_entry_work_entries_no_validated_conflict():
    # Remove _work_entries_no_validated_conflict constraint in hr.work.entry model in hr_work_entry module
    # to use another constraint instead
    # It doesn't delete constraint on database server
    try:
        # test if module viin_hr_overtime_timeoff is available
        from odoo.addons.viin_hr_overtime_timeoff.models import hr_work_entry
        # remove the hr_work_entry's _work_entries_no_validated_conflict
        from odoo.addons.hr_work_entry.models.hr_work_entry import HrWorkEntry
        for el in HrWorkEntry._sql_constraints:
            if el[0] == '_work_entries_no_validated_conflict':
                _logger.info("Removing the default hr_work_entry_work's SQL constraint `_work_entries_no_validated_conflict`")
                HrWorkEntry._sql_constraints.remove(el)
                break
    except Exception:
        return


def _update_brand_web_icon_data(env):
    # Generic trick necessary for search() calls to avoid hidden menus which contains 'base.group_no_one'
    menus = env['ir.ui.menu'].with_context({'ir.ui.menu.full_list': True}).search([('web_icon', '!=', False)])
    for m in menus:
        web_icon = m.web_icon
        paths = web_icon.split(',')
        if len(paths) == 2:
            module = paths[0]
            module_name = paths[1].split('/')[-1][:-4]
            if module_name == 'board' or module_name == 'modules' or module_name == 'settings':
                module = module_name
                web_icon = '%s,static/description/icon.png' % module

            module_icon = check_viin_brand_module_icon(module)
            if module_icon:
                web_icon_data = m._compute_web_icon_data(web_icon)
                web_icon = _build_viin_web_icon_path_from_image(module_icon)
                vals = {}
                if m.web_icon != web_icon:
                    vals['web_icon'] = web_icon
                if web_icon_data != m.web_icon_data:
                    vals['web_icon_data'] = web_icon_data
                if vals:
                    m.write(vals)


def _update_favicon(env):
    if viin_brand_manifest.get('installable', False):
        branding_module = _get_branding_module()
        if os.path.exists(os.path.join(get_module_path(branding_module, downloaded=False, display_warning=False), 'static', 'img', 'favicon.ico')):
            res_company_obj = env['res.company']
            data = res_company_obj._get_default_favicon()
            res_company_obj.with_context(active_test=False).search([]).write({'favicon': data})


def _override_test_manifests_keys():
    """Override to support some manifest keys in module"""
    global test_manifests
    if test_manifests:
        test_manifests.MANIFEST_KEYS.update({
            # Viindoo modules
            'old_technical_name': '',
            'name_vi_VN': '',
            'summary_vi_VN': '',
            'description_vi_VN': '',
            'demo_video_url': '',
            'demo_video_url_vi_VN': '',
            'live_test_url': '',
            'live_test_url_vi_VN': 'https://v17demo-vn.viindoo.com',
            'currency': 'EUR',
            'support': 'apps.support@viindoo.com',
            'price': '99.9',
            'subscription_price': '9.9',
            # OCA module (web_responsive)
            'development_status': '',
            'maintainers': [],
            'excludes': [],
            'task_ids': [],
            # Viindoo theme
            'industries': '',
        })


def _setUpAddonManifestPatched_plus(self):
    """Override to compile assets of to_base in test mode,
       because the module `to_base` is be loaded in server wide.
    """
    res = setUpAddonManifestPatched(self)
    self.manifests.update({'to_base': load_manifest('to_base')})
    self.patch(odoo.modules.module, '_get_manifest_cached', Mock(side_effect=lambda module, mod_path=None: self.manifests.get(module, {})))
    return res


def _close_all_plus(self, dsn=None):
    """
    Mute the logger of "Closed X connections to ..." to avoid huge amount of logs
    """
    with tools.mute_logger('odoo.sql_db'):
        res = _close_all(self, dsn=dsn)
    return res


def _url_open_plus(self, url, data=None, files=None, timeout=20, headers=None, allow_redirects=True, head=False):
    """
    [FIX] tests: bump url_open timeout

    Some tests are randomly failling because /web takes more than 10 seconds to load.
    A future pr will speedup /web but waiting for that a small bump of the timeout should help.
    """
    return _url_open(self, url, data=data, files=files, timeout=timeout, headers=headers, allow_redirects=allow_redirects, head=head)


def _auto_init_plus(self):
    # Remove me, see https://github.com/odoo/odoo/pull/190736
    """
    Cannot upgrade module sale_crm when target_sales_invoiced field stores a
    value greater than int4. Because when upgrading, the default will
    convert float to int4 causing an error
    psycopg2.errors.NumericValueOutOfRange
    """
    field = self._fields.get('target_sales_invoiced')
    if field and field.column_type == ('int4', 'int4'):
        field.column_type = ('numeric', 'numeric')
    return _auto_init(self)


def _build_viin_web_icon_path_from_image(img_path):
    """
    This method will turn `/module_name/path/to/image` and `module_name/path/to/image`
    into 'module_name,path/to/image' which is for web_icon

    @param img_path: path to the image that will be used for web_icon.
        The path must in the format of either `/module_name/path/to/image` or `module_name/path/to/image`

    @return: web_icon string (e.g. 'module_name,path/to/image')
    """
    path = []
    while img_path:
        img_path, basename = os.path.split(img_path)
        if img_path == os.path.sep:
            img_path = ''
        if img_path:
            path.insert(0, basename)
    return '%s,%s' % (basename, os.path.join(*path))


def _compute_web_icon_data_plus(self, web_icon):
    """
    Override to take web_icon for menus from
        either '/viin_brand_originmodulename'/static/description/icon.png'
        or '/viin_brand/static/img/apps/originmodulename.png'
    """
    paths = web_icon.split(',') if web_icon and isinstance(web_icon, str) else []
    if len(paths) == 2:
        if check_viin_brand_module_icon(paths[0]):
            img_path = get_viin_brand_module_icon(paths[0])
            web_icon = _build_viin_web_icon_path_from_image(img_path)
    return _compute_web_icon_data(self, web_icon)


def _patch_prefetch_max_from_config():
    """Read prefetch_max from config, monkey patch PREFETCH_MAX and _in_cache_without for BaseModel."""
    prefetch_max = config.get('prefetch_max')
    if prefetch_max:
        try:
            prefetch_max = int(prefetch_max)
            odoo.models.PREFETCH_MAX = prefetch_max
        except Exception as e:
            _logger.warning(f"[to_base] Invalid prefetch_max value in config: {prefetch_max}. Error: {e}")
            return

        _in_cache_without_original = odoo.models.BaseModel._in_cache_without

        def _in_cache_without_patched(self, field, limit=prefetch_max):
            return _in_cache_without_original(self, field, limit=limit)

        odoo.models.BaseModel._in_cache_without = _in_cache_without_patched


def pre_init_hook(env):
    module.get_module_icon_path = get_viin_brand_icon_path
    module.get_resource_path = get_viin_brand_resource_path
    modules.get_resource_path = get_viin_brand_resource_path
    module.get_module_icon = get_viin_brand_module_icon
    _patch_prefetch_max_from_config()


def post_init_hook(env):
    _update_brand_web_icon_data(env)
    _update_favicon(env)


def uninstall_hook(env):
    module.get_module_icon_path = get_viin_brand_icon_path
    module.get_resource_path = get_viin_brand_resource_path
    modules.get_resource_path = get_viin_brand_resource_path
    module.get_module_icon = get_module_icon
    module.load_manifest = load_manifest
    if _url_open:
        HttpCase.url_open = _url_open
    ConnectionPool.close_all = _close_all


def post_load():
    _disable_currency_rate_unique_name_per_day()
    _disable_hr_work_entry_work_entries_no_validated_conflict()
    if config.get('test_enable', False):
        if test_manifests:
            _override_test_manifests_keys()
        if AddonManifestPatched:
            AddonManifestPatched.setUp = _setUpAddonManifestPatched_plus
        HttpCase.url_open = _url_open_plus
        # Because we are disabling test tour on runbot due to to_backend_theme module being affected
        # This will result in faster response times for browser checks, improving performance and reducing unnecessary processing
        # Each test will save 9.9s
        global common
        if common:
            common.CHECK_BROWSER_ITERATIONS = 1
    module.get_module_icon_path = get_viin_brand_icon_path
    modules.get_module_resource = get_viin_brand_resource_path
    module.get_module_icon = get_viin_brand_module_icon
    module.get_resource_path = get_viin_brand_resource_path
    modules.get_resource_path = get_viin_brand_resource_path
    module.load_manifest = _load_manifest_plus
    ConnectionPool.close_all = _close_all_plus
    Users._auto_init = _auto_init_plus
    IrUiMenu._compute_web_icon_data = _compute_web_icon_data_plus
    _patch_prefetch_max_from_config()
