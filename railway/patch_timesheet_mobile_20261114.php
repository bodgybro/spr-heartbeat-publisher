<?php
/**
 * iPhone/iPad multi-page PDF printing fix for existing Claim Checker timesheet.
 * Only changes how the generated PDF opens on iOS; desktop and PDF build unchanged.
 */
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(403); exit; }
$home=getenv('HOME') ?: '';
$root=realpath($home.'/public_html/claim_checker');
if(!$root||!is_file($root.'/index.php')){fwrite(STDERR,"STOP: Claim Checker folder missing.\n");exit(1);}
$script=$root.'/timesheet/timesheet-print.js';
$index=$root.'/index.php';
$reader=$home.'/public_html/sps/check/reader.js';
foreach([$script,$index,$reader] as $file)if(!is_file($file)||is_link($file)){fwrite(STDERR,"STOP: Invalid ".$file."\n");exit(1);}
$source=file_get_contents($script);
$html=file_get_contents($index);
$readerSource=file_get_contents($reader);
if($source===false||$html===false||$readerSource===false){fwrite(STDERR,"STOP: Cannot read source.\n");exit(1);}
if(str_contains($source,'TIMESHEET_IOS_FULL_PDF_20261114')){echo "ALREADY INSTALLED: No changes.\n";exit(0);}
$needle="tab.document.getElementById('viewer').src=url;";
if(substr_count($source,$needle)!==1){fwrite(STDERR,"STOP: PDF viewer assignment not uniquely identified.\n");exit(1);}
$insert=<<<'JS'
        // TIMESHEET_IOS_FULL_PDF_20261114: iOS sometimes prints only iframe page 1.
        // Open complete generated PDF in the native viewer; leave desktop unchanged.
        const ua=String(navigator.userAgent||'');
        const iosPdf=/iPad|iPhone|iPod/i.test(ua) ||
          (/Macintosh/i.test(ua) && Number(navigator.maxTouchPoints||0)>1);
        if(iosPdf){
          const status=tab.document.getElementById('status');
          status.textContent='Opening complete PDF. Use Share / Print for both pages.';
          const link=tab.document.createElement('a');
          link.href=url;link.textContent='Open full PDF';link.target='_self';
          link.style.cssText='display:inline-block;padding:9px 14px;border-radius:5px;background:#ffa800;color:#191919;font-weight:bold;text-decoration:none';
          tab.document.querySelector('.bar').appendChild(link);
          try{tab.location.replace(url);}catch(_){status.textContent='Tap Open full PDF, then Share / Print.';}
          return;
        }
JS;
$newSource=str_replace($needle,$insert."\n".$needle,$source);
// Keep the server's SPR/Claim Checker permission checks untouched.
// Change this client-side reader role gate ONLY within the protected Claim Checker page.
if(!str_contains($html,"spr_access_has('claimChecker')")){
  fwrite(STDERR,"STOP: Claim Checker server permission guard not recognised.\n");exit(1);
}
$readerGate="if(!allowed)throw Error('Admin or Tester account required.');";
if(substr_count($readerSource,$readerGate)!==1){
  fwrite(STDERR,"STOP: Reader role guard changed; originals intact.\n");exit(1);
}
$readerNewGate="if(!allowed&&!/^\\/claim_checker(?:\\/|$)/.test(location.pathname))throw Error('Admin or Tester account required.');";
$newReader=str_replace($readerGate,$readerNewGate,$readerSource);
$count=0;
$newHtml=preg_replace('~(timesheet/timesheet-print\.js\?v=)[A-Za-z0-9._-]+~','$1TS-IOS-2P-20261114',$html,1,$count);
if($count!==1||!is_string($newHtml)){fwrite(STDERR,"STOP: Timesheet cache reference not uniquely identified.\n");exit(1);}
$readerRefCount=0;
$newHtml=preg_replace('~(\.\./sps/check/reader\.js\?v=)[A-Za-z0-9._-]+~','$1CHECK3-CLAIMACCESS-20261114',$newHtml,1,$readerRefCount);
if($readerRefCount!==1||!is_string($newHtml)){
  fwrite(STDERR,"STOP: Reader script cache reference not uniquely identified.\n");exit(1);
}
$backups=$home.'/sps-working-backups';
if(!is_dir($backups)||is_link($backups)){fwrite(STDERR,"STOP: Working backup folder missing.\n");exit(1);}
$rollback=$backups.'/before-timesheet-ios-2p-'.date('Ymd-His').'-'.bin2hex(random_bytes(3));
if(!mkdir($rollback,0700)){fwrite(STDERR,"STOP: Cannot create rollback folder.\n");exit(1);}
foreach([$script=>$source,$index=>$html,$reader=>$readerSource] as $file=>$data){
  if(file_put_contents($rollback.'/'.basename($file),$data,LOCK_EX)!==strlen($data)){
    fwrite(STDERR,"STOP: Backup copy failed. Originals untouched.\n");exit(1);
  }
  chmod($rollback.'/'.basename($file),0600);
}
$staged=[];
foreach([$script=>$newSource,$index=>$newHtml,$reader=>$newReader] as $file=>$data){
  $tmp=$file.'.ios-two-page-'.bin2hex(random_bytes(4));
  if(file_put_contents($tmp,$data,LOCK_EX)!==strlen($data)){fwrite(STDERR,"STOP: Could not stage update.\n");exit(1);}
  chmod($tmp,fileperms($file)&0777);
  $staged[$file]=$tmp;
}
$node=trim((string)shell_exec('command -v node 2>/dev/null'));
if($node!==''){
  $output=[];$rc=0;
  exec(escapeshellarg($node).' --check < '.escapeshellarg($staged[$script]).' 2>&1',$output,$rc);
  if($rc!==0){fwrite(STDERR,"STOP: JavaScript syntax check failed. No changes.\n");exit(1);}
}
if($node!==''){
  $output=[];$rc=0;
  exec(escapeshellarg($node).' --check < '.escapeshellarg($staged[$reader]).' 2>&1',$output,$rc);
  if($rc!==0){fwrite(STDERR,"STOP: Roster reader JS syntax invalid; no changes.\n");exit(1);}
}
$done=[];
foreach($staged as $file=>$tmp){
  if(!rename($tmp,$file)){
    foreach($done as $original)file_put_contents($original,$original===$index?$html:($original===$reader?$readerSource:$source),LOCK_EX);
    fwrite(STDERR,"STOP: Installation failed, prior files restored. Backup: $rollback\n");exit(1);
  }
  $done[]=$file;
}
echo "PASS: iPhone/iPad full timesheet PDF + authorised Claim Checker reader installed.\n";
echo "Desktop printing and PDF generation unchanged.\n";
echo "Rollback: $rollback\n";
