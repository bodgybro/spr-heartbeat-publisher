<?php
/**
 * Enable ROC manual-update controls on one cPanel SPR Search site.
 * PHP CLI: php patch_sps_admin_roc.php /home/ACCOUNT/public_html/sps
 */
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(403); exit; }
$root = isset($argv[1]) ? realpath($argv[1]) : false;
$home = getenv('HOME');
$allowed = $home ? realpath($home . '/public_html/sps') : false;
if (!$root || !$allowed || $root !== $allowed) { fwrite(STDERR,"STOP: Give this account's exact ~/public_html/sps directory.\n"); exit(1); }
$files = ['index.php','admin.js','admin-api.php'];
$src = [];
foreach($files as $file) {
  $path = $root . '/' . $file;
  if (!is_file($path) || is_link($path)) { fwrite(STDERR,"STOP: Invalid original $file\n"); exit(1); }
  $src[$file] = file_get_contents($path);
  if ($src[$file]===false) exit(1);
}
if (str_contains($src['admin.js'],'adminRocUpdateButton') || str_contains($src['index.php'],'adminRocUpdateButton')) {
  fwrite(STDERR,"STOP: ROC button appears to be installed already. No files changed.\n"); exit(1);
}
function once(string $src, string $old, string $new, string $label): string {
    $num=substr_count($src,$old);
    if ($num!==1) throw new RuntimeException("Expected exactly one $label anchor; found $num");
    return str_replace($old,$new,$src);
}
function rxonce(string $src,string $pattern,callable $replacement,string $label):string {
    $matches=[];
    $n=preg_match_all($pattern,$src,$matches,PREG_SET_ORDER);
    if ($n!==1) throw new RuntimeException("Expected one $label pattern; found ".var_export($n,true));
    return preg_replace_callback($pattern,$replacement,$src,1);
}
$installed=[];
try {
  $index=$src['index.php'];
  $index=rxonce($index,'/(^[ \t]*)(<button\b[^>]*\bid="adminRosterUpdateButton"[^>]*>Update Rosters<\/button>)/m',
    fn($m)=>$m[0]."\n".$m[1].'<button id="adminRocUpdateButton" class="button ghost" type="button">Update ROC</button>', 'Update Rosters button');
  $index=rxonce($index,'/(^[ \t]*)(<div\b[^>]*\bid="adminRosterUpdateStatus"[^>]*><\/div>)/m',
    fn($m)=>$m[0]."\n".$m[1].'<div id="adminRocUpdateStatus" class="admin-status"></div>', 'roster update status');
  $index=rxonce($index, '/(\bsrc=["\'])(admin\.js(?:\?[^"\']*)?)(["\'])/',
    function($m){$sep=str_contains($m[2],'?')?'&':'?';return $m[1].$m[2].$sep.'manualroc=20261114'.$m[3];}, 'admin.js script reference');
  $js=$src['admin.js'];
  $js=once($js,"['adminUpdateButton','adminRosterUpdateButton']","['adminUpdateButton','adminRosterUpdateButton','adminRocUpdateButton']",'button busy-state list');
  $js=once($js,"function commandLabel(command){return command==='rosters'?'Roster':'SPR';}",
    "function commandLabel(command){return command==='roc'?'ROC':(command==='rosters'?'Roster':'SPR');}\n".
    "function onlineStatusElement(command){return el(command==='roc'?'adminRocUpdateStatus':(command==='rosters'?'adminRosterUpdateStatus':'adminUpdateStatus'));}\n".
    "function clearOtherOnlineStatusFields(exclude){for(const id of ['adminUpdateStatus','adminRosterUpdateStatus','adminRocUpdateStatus']){const node=el(id);if(node&&node!==exclude)node.textContent='';}}",
    'command label and status helper');
  $js=once($js,"const own=type==='rosters'?el('adminRosterUpdateStatus'):el('adminUpdateStatus');\n          const other=type==='rosters'?el('adminUpdateStatus'):el('adminRosterUpdateStatus');",
    "const own=onlineStatusElement(type);",
    'remote command display');
  $js=once($js,"if(other)other.textContent='';", "clearOtherOnlineStatusFields(own);",'clear stale statuses');
  $js=once($js,"const done=observedRemoteCommand.command==='rosters'?el('adminRosterUpdateStatus'):el('adminUpdateStatus');",
    "const done=onlineStatusElement(observedRemoteCommand.command);",'observed completion display');
  $js=once($js,"el('adminRosterUpdateButton').addEventListener('click',()=>requestOnlineUpdate('rosters','adminRosterUpdateStatus','Roster'));",
    "el('adminRosterUpdateButton').addEventListener('click',()=>requestOnlineUpdate('rosters','adminRosterUpdateStatus','Roster'));\n".
    "el('adminRocUpdateButton').addEventListener('click',()=>requestOnlineUpdate('roc','adminRocUpdateStatus','ROC'));",'new ROC click handler');
  $js=once($js,"if(el('adminRosterUpdateStatus'))el('adminRosterUpdateStatus').textContent='Cancelling update…';",
    "const cancelledStatus=onlineStatusElement(activeOnlineCommand?.command||observedRemoteCommand?.command);\n    if(cancelledStatus)cancelledStatus.textContent='Cancelling update…';",'cancel status');
  $api=once($src['admin-api.php'],"['spr','rosters']","['spr','rosters','roc']",'admin API command allowlist');
  $updated=['index.php'=>$index,'admin.js'=>$js,'admin-api.php'=>$api];
  $backupRoot=$home.'/sps-working-backups';
  if (!is_dir($backupRoot)) throw new RuntimeException('New working backup directory not found: '.$backupRoot);
  $dir=$backupRoot.'/pre-manual-roc-'.date('Ymd-His').'-'.substr(bin2hex(random_bytes(3)),0,6);
  if (!mkdir($dir,0700)) throw new RuntimeException('Cannot make rollback directory');
  foreach($src as $name=>$body) {
    if (file_put_contents($dir.'/'.$name,$body,LOCK_EX)!==strlen($body)) throw new RuntimeException('Backup copy failed: '.$name);
    chmod($dir.'/'.$name,0600);
  }
  $check=$dir.'/.manual-roc-syntax-'.bin2hex(random_bytes(5)).'.php';
  file_put_contents($check,$api,LOCK_EX);
  exec('php -l '.escapeshellarg($check).' 2>&1',$lint,$rc);
  @unlink($check);
  if ($rc!==0) throw new RuntimeException('Patched admin-api.php failed lint: '.implode(' ',$lint));
  foreach($updated as $name=>$body) {
    $dst=$root.'/'.$name;
    $tmp=$dst.'.manual-roc-'.bin2hex(random_bytes(5));
    if (file_put_contents($tmp,$body,LOCK_EX)!==strlen($body)) throw new RuntimeException('Cannot write $tmp');
    chmod($tmp,fileperms($dst)&0777);
    if(!rename($tmp,$dst)) throw new RuntimeException('Cannot replace '.$dst);
    $installed[]=$name;
  }
  echo "PASS: ROC Admin controls installed in $root\nRollback copies: $dir\n";
  echo "Remember: only test after Cloudflare and Railway ROC command support are deployed.\n";
} catch(Throwable $e) {
  foreach ($installed as $name) { @file_put_contents($root.'/'.$name,$src[$name],LOCK_EX); }
  fwrite(STDERR,"STOP: ".$e->getMessage()."\n");
  exit(1);
}
