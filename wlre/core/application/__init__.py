"""純核心公開入口；桌面轉接器由外部組裝，不由核心載入。"""
from wlre.core.application.configuration import ApplicationConfiguration
from wlre.core.application.modules import (
           Lifecycle,
           LifecycleError,
           ManagedModule,
           ModuleSpec,
)
from wlre.core.application.runtime import Application

__all__ = ('Application', 'ApplicationConfiguration', 'Lifecycle', 'LifecycleError',
           'ManagedModule', 'ModuleSpec')
