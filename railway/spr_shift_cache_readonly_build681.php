<?php
declare(strict_types=1);
// Build 681: serve an indexed, checksum-matched ORIGINAL shift-PDF manifest.
// Read-only. Static .json responses are blocked on this host; PHP can read
// the same private filesystem data without reprocessing the full PDF.
header('Content-Type: application/json; charset=UTF-8');
header('Cache-Control: no-store, max-age=0');
header('X-Content-Type-Options: nosniff');
function result_json(int $status,array $data):void {
    http_response_code($status);
    echo json_encode($data,JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
    exit;
}
$role=$_GET['role']??'';
$date=$_GET['date']??'';
if (!is_string($role)||!preg_match('/\A[dg]\z/D',$role)||
    !is_string($date)||!preg_match('/\A20\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\z/D',$date)) {
    result_json(400,['ok'=>false,'error'=>'Invalid date or role']);
}
$manifestPath=__DIR__.'/spr/x/'.$role.'/'.$date.'/manifest.json';
$metaPath=__DIR__.'/spr/i/'.$role.'/'.$date.'.meta.json';
if (!is_file($manifestPath)||!is_file($metaPath)) {
    result_json(404,['ok'=>false,'error'=>'Shift PDFs not prepared for this SPR']);
}
if (filesize($manifestPath)>256000||filesize($metaPath)>128000) {
    result_json(409,['ok'=>false,'error'=>'Shift manifest exceeds expected size']);
}
$m=json_decode((string)file_get_contents($manifestPath),true);
$index=json_decode((string)file_get_contents($metaPath),true);
if (!is_array($m)||!is_array($index)||($m['version']??null)!==680||
    ($m['date']??'')!==$date||($m['role']??'')!==$role||
    !is_array($m['shifts']??null)||!is_string($m['sourceSha']??null)||
    !preg_match('/\A[a-f0-9]{64}\z/i',$m['sourceSha'])||
    !hash_equals(strtolower((string)($index['sourceSha']??'')),strtolower($m['sourceSha']))) {
    result_json(409,['ok'=>false,'error'=>'Shift cache is not matched to the current SPR index']);
}
result_json(200,$m);
