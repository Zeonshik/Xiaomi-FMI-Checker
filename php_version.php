<?php

$BOT_TOKEN = "YOUR_TOKEN_FROM_@botfather";
$API_URL = "https://api.telegram.org/bot$BOT_TOKEN/";

$CHANNEL_USERNAME = "your channel's username";
$CHANNEL_URL = "https://t.me/your channel's username";

$ERROR_TRANSLATIONS = [
    "设备参数错误" => "Invalid device parameters.",
    "参数错误" => "Invalid request parameters.",
    "imei 参数错误" => "Invalid IMEI.",
    "设备不存在" => "Device not found.",
    "未找到设备信息" => "Device information not found.",
    "系统繁忙，请稍后再试" => "Xiaomi service is busy. Try again later.",
    "服务暂不可用" => "Xiaomi service is temporarily unavailable.",
];

$update = json_decode(file_get_contents("php://input"), true);

function apiRequest($method, $data = []) {
    global $API_URL;

    $ch = curl_init($API_URL . $method);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, $data);
    $response = curl_exec($ch);
    curl_close($ch);

    return json_decode($response, true);
}

function sendMessage($chat_id, $text, $reply_markup = null) {
    $data = [
        "chat_id" => $chat_id,
        "text" => $text
    ];

    if ($reply_markup) {
        $data["reply_markup"] = json_encode($reply_markup);
    }

    return apiRequest("sendMessage", $data);
}

function editMessage($chat_id, $message_id, $text) {
    return apiRequest("editMessageText", [
        "chat_id" => $chat_id,
        "message_id" => $message_id,
        "text" => $text
    ]);
}

function isValidIMEI($imei) {
    return ctype_digit($imei) && strlen($imei) == 15;
}

function normalizeIMEI($text) {
    return preg_replace('/\D/', '', $text);
}

function translateError($msg) {
    global $ERROR_TRANSLATIONS;

    foreach ($ERROR_TRANSLATIONS as $cn => $en) {
        if (strpos($msg, $cn) !== false) {
            return $en;
        }
    }

    return $msg ?: "Unknown API error.";
}

function checkSubscription($user_id) {
    global $CHANNEL_USERNAME;

    $res = apiRequest("getChatMember", [
        "chat_id" => $CHANNEL_USERNAME,
        "user_id" => $user_id
    ]);

    if (!$res["ok"]) {
        return [false, "Bot must be admin in channel."];
    }

    $status = $res["result"]["status"];
    if (in_array($status, ["creator", "administrator", "member"])) {
        return [true, ""];
    }

    return [false, "Subscribe to channel first."];
}

function subscribeKeyboard() {
    global $CHANNEL_URL;

    return [
        "inline_keyboard" => [
            [
                ["text" => "Subscribe", "url" => $CHANNEL_URL]
            ],
            [
                ["text" => "Check subscription", "callback_data" => "check_sub"]
            ]
        ]
    ];
}

function fetchFMI($imei) {
    $ts = round(microtime(true) * 1000);
    $url = "https://i.mi.com/support/anonymous/status?ts=$ts&id=$imei";

    $headers = [
        "Accept: */*",
        "Referer: https://i.mi.com/find/device/activationlock",
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie: uLocale=en_US; iplocale=en_US"
    ];

    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 20);
    curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

    $response = curl_exec($ch);

    if (curl_errno($ch)) {
        curl_close($ch);
        return [false, "Request error"];
    }

    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($httpCode !== 200) {
        return [false, "Service unavailable"];
    }

    $json = json_decode($response, true);

    if (!isset($json["code"]) || !in_array($json["code"], [0, 200])) {
        return [false, translateError($json["description"] ?? "")];
    }

    $data = $json["data"];

    $locked = !empty($data["locked"]);
    $fmi = $locked ? "ON" : "OFF";

    $text = "📱 IMEI: $imei\n🔒 FMI: $fmi";

    if (!empty($data["model"])) {
        $text .= "\nModel: " . $data["model"];
    }
    if (!empty($data["country"])) {
        $text .= "\nRegion: " . $data["country"];
    }

    return [true, $text];
}

if (isset($update["message"])) {

    $chat_id = $update["message"]["chat"]["id"];
    $user_id = $update["message"]["from"]["id"];
    $text = trim($update["message"]["text"] ?? "");

    if ($text == "/start" || $text == "/help") {
        sendMessage($chat_id,
            "Send /check <imei>",
            subscribeKeyboard()
        );
        exit;
    }

    if (strpos($text, "/check") === 0) {

        list($ok, $err) = checkSubscription($user_id);
        if (!$ok) {
            sendMessage($chat_id, $err, subscribeKeyboard());
            exit;
        }

        $parts = explode(" ", $text);
        if (empty($parts[1])) {
            sendMessage($chat_id, "Send IMEI after command");
            exit;
        }

        $imei = normalizeIMEI($parts[1]);

        if (!isValidIMEI($imei)) {
            sendMessage($chat_id, "Invalid IMEI");
            exit;
        }

        $msg = sendMessage($chat_id, "Checking $imei...");

        list($ok, $result) = fetchFMI($imei);

        editMessage($chat_id, $msg["result"]["message_id"], $result);
    }
}

if (isset($update["callback_query"])) {
    $cb = $update["callback_query"];
    $chat_id = $cb["message"]["chat"]["id"];
    $user_id = $cb["from"]["id"];

    list($ok, $err) = checkSubscription($user_id);

    if ($ok) {
        sendMessage($chat_id, "Subscription confirmed");
    } else {
        sendMessage($chat_id, $err, subscribeKeyboard());
    }
}
