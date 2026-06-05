from feishu_browser_use.task.executor import TaskExecutor


def test_successful_backend_open_is_not_login_required():
	result = "已成功打开美团外卖商家后台主页，当前页面显示商家首页，可正常使用。"

	assert TaskExecutor._detect_login_required(None, result) is False


def test_already_logged_in_success_is_not_login_required():
	result = "已登录并成功打开美团外卖商家后台主页。"

	assert TaskExecutor._detect_login_required(None, result) is False


def test_explicit_login_blocker_is_login_required():
	result = "当前停留在登录页，需要重新登录后才能继续。"

	assert TaskExecutor._detect_login_required(None, result) is True
