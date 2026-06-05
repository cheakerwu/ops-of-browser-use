from feishu_browser_use.intent import IntentParser


def test_parse_open_backend_intent():
	result = IntentParser().parse(
		raw_text="打开美团江湖饭焗",
		platform="meituan",
		instruction="打开",
	)

	assert result.intent == "open_merchant_backend"
	assert result.target == "merchant_backend"
	assert result.params == {}
	assert result.confidence == 0.95


def test_parse_change_price_intent():
	result = IntentParser().parse(
		raw_text="把美团江湖饭焗咖啡价格改成25元",
		platform="meituan",
		instruction="咖啡价格改成25元",
	)

	assert result.intent == "change_price"
	assert result.target == "咖啡"
	assert result.params == {"price": 25.0}
	assert result.confidence == 0.9


def test_parse_update_image_intent_is_reserved():
	result = IntentParser().parse(
		raw_text="上传图片替换美团江湖饭焗门店图",
		platform="meituan",
		instruction="上传图片替换门店图",
	)

	assert result.intent == "update_image"
	assert result.target == "门店图"
	assert result.params == {}
	assert result.confidence == 0.8


def test_parse_unknown_intent_has_low_confidence():
	result = IntentParser().parse(
		raw_text="帮我看看",
		platform="meituan",
		instruction="帮我看看",
	)

	assert result.intent == "general_task"
	assert result.target == ""
	assert result.confidence == 0.3
