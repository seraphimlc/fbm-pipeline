#!/usr/bin/env python3
"""大健云仓素材包下载 v5

v5 修复：
1. 修复普通产品下载超时：先记录existing_zips再点击下载按钮
2. 每次点击选项会下载2个zip（image+file + information），等待所有下载完成
3. 更健壮的弹出框检测：兼容中文标签
4. 简化流程：一次打开页面，检测选项，逐个下载
"""

import subprocess
import glob
import shutil
import zipfile
import time
import sys
import os
import json

# 所有支持的下载类型
DOWNLOAD_TYPES = {
    'to_b': {
        'label': 'To B素材包',
        'select_text': 'To B素材包',
        'zip_patterns': ['*_image+file_*.zip', '*_Image+File_*.zip'],
    },
    'retail_ready': {
        'label': 'Retail Ready素材包',
        'select_text': 'Retail Ready素材包',
        'zip_patterns': ['*_Retail_Ready_Image+File_*.zip', '*_Retail_Ready_image+file_*.zip'],
    },
    'information': {
        'label': 'Information资料包',
        'select_text': 'Information',
        'zip_patterns': ['*_information_*.zip', '*_Information_*.zip'],
    },
}

DOWNLOADS_DIR = '/Users/jiyuhang/Downloads'


def run_js(js_code):
    """在Chrome当前页面执行JS并返回结果（已弃用，使用run_js_file代替）"""
    return run_js_file(js_code)


def run_js_file(js_code):
    """在Chrome当前页面执行JS（通过文件方式，避免转义问题）"""
    js_path = '/tmp/gigab2b_dl.js'
    with open(js_path, 'w') as f:
        f.write(js_code)
    cat_cmd = 'cat ' + js_path
    osascript = 'tell application "Google Chrome"\n' \
        '    tell active tab of front window\n' \
        '        set jsFile to do shell script "' + cat_cmd + '"\n' \
        '        set result to execute javascript jsFile\n' \
        '        return result\n' \
        '    end tell\n' \
        'end tell'
    result = subprocess.run(['osascript', '-e', osascript], capture_output=True, text=True)
    return result.stdout.strip()


def get_item_code_from_page():
    """从当前页面获取Item Code（如W3662P363292）"""
    js = '''(function() {
    var allText = document.body.innerText;
    var lines = allText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
    for (var i = 0; i < lines.length; i++) {
        if (lines[i] === 'Item Code:' || lines[i].match(/^Item Code\\s*:/)) {
            return lines[i + 1] || '';
        }
    }
    var codeMatch = allText.match(/W[0-9]{4}[A-Z][0-9]{5,6}/);
    return codeMatch ? codeMatch[0] : '';
})()'''
    result = run_js_file(js)
    return result if result and result != 'missing value' else None


def navigate_to_product(product_id):
    """用AppleScript让Chrome跳转到商品页面"""
    url = f"https://www.gigab2b.com/index.php?route=product/product&product_id={product_id}"
    osascript = f'''tell application "Google Chrome"
    tell active tab of front window
        set URL to "{url}"
    end tell
end tell'''
    subprocess.run(['osascript', '-e', osascript], capture_output=True, text=True)
    # 等待页面加载
    time.sleep(3)
    for _ in range(10):
        osascript = '''tell application "Google Chrome"
    tell active tab of front window
        execute javascript "(document.querySelector('button') !== null).toString()"
    end tell
end tell'''
        result = subprocess.run(['osascript', '-e', osascript], capture_output=True, text=True)
        if result.stdout.strip() == 'true':
            return True
        time.sleep(1)
    return False


def click_download_button():
    """点击"下载素材包"按钮

    Returns:
        bool: 是否成功点击
    """
    js = '''(function() {
    var btns = document.querySelectorAll('button');
    var lastBtn = null;
    for (var i = 0; i < btns.length; i++) {
        if (btns[i].innerText.includes('下载素材包')) {
            var rect = btns[i].getBoundingClientRect();
            if (rect.top > 0 && rect.left > 0) {
                lastBtn = btns[i];
            }
        }
    }
    if (lastBtn) {
        lastBtn.click();
        return 'true';
    }
    return 'false';
})()'''
    result = run_js_file(js)
    return result == 'true'


def get_popup_options():
    """检测弹出框中的所有选项（不点击下载按钮，只读取）

    Returns:
        list: 弹出框中的选项文本列表，空列表表示普通产品（无弹出框/已直接下载），
              None表示未找到下载按钮
    """
    js = '''(function() {
    var options = [];
    var popovers = document.querySelectorAll('.resource-type-class');
    var popover = null;
    for (var i = 0; i < popovers.length; i++) {
        if (popovers[i].offsetHeight > 0) {
            popover = popovers[i];
            break;
        }
    }
    if (popover) {
        var items = popover.querySelectorAll('div.cursor-pointer');
        items.forEach(function(item) {
            options.push(item.innerText.trim());
        });
    }
    return JSON.stringify(options);
})()'''
    result = run_js_file(js)
    try:
        all_options = json.loads(result)
    except Exception:
        all_options = []

    # 在Python端过滤：只保留DOWNLOAD_TYPES中定义的选项
    target_texts = [info['select_text'] for info in DOWNLOAD_TYPES.values()]
    options = [t for t in all_options if t in target_texts]

    return options


def click_popup_option(option_text):
    """点击弹出框中指定文本的选项

    Args:
        option_text: 选项文本

    Returns:
        bool: 是否成功点击
    """
    # 将中文文本编码为Unicode转义，避免AppleScript编码问题
    js = '''(function() {
    var targetText = ''' + json.dumps(option_text) + ''';
    var popovers = document.querySelectorAll('.resource-type-class');
    var popover = null;
    for (var i = 0; i < popovers.length; i++) {
        if (popovers[i].offsetHeight > 0) {
            popover = popovers[i];
            break;
        }
    }
    if (!popover && popovers.length > 0) {
        popover = popovers[popovers.length - 1];
        popover.style.display = 'block';
        popover.style.visibility = 'visible';
        popover.style.opacity = '1';
    }
    if (!popover) return 'false';
    var items = popover.querySelectorAll('div.cursor-pointer');
    for (var i = 0; i < items.length; i++) {
        if (items[i].innerText.trim() === targetText) {
            items[i].click();
            return 'true';
        }
    }
    return 'false';
})()'''
    result = run_js_file(js)
    return result == 'true'


def wait_for_downloads(timeout=120, existing_zips=None):
    """等待所有下载完成

    Args:
        timeout: 超时秒数
        existing_zips: 下载前已有的zip列表

    Returns:
        list: 新下载的zip文件路径列表
    """
    if existing_zips is None:
        existing_zips = set()

    start_time = time.time()
    last_progress = 0

    while time.time() - start_time < timeout:
        # 检查是否还有.crdownload文件
        crdownloads = glob.glob(os.path.join(DOWNLOADS_DIR, '*.crdownload'))

        # 查找新增的zip文件
        all_zips = set()
        for type_info in DOWNLOAD_TYPES.values():
            for pattern in type_info['zip_patterns']:
                all_zips |= set(glob.glob(os.path.join(DOWNLOADS_DIR, pattern)))

        new_zips = all_zips - existing_zips

        # 进度报告（每10秒一次）
        now = time.time()
        if now - last_progress > 10:
            elapsed = int(now - start_time)
            if crdownloads:
                print(f"  ⏳ 下载中... ({elapsed}秒, {len(crdownloads)}个文件)")
            elif not new_zips:
                print(f"  ⏳ 等待下载... ({elapsed}秒)")
            last_progress = now

        # 没有正在下载的文件 + 至少有一个新zip → 确认完成
        if not crdownloads and new_zips:
            time.sleep(3)  # 多等一下，可能有多个文件
            crdownloads = glob.glob(os.path.join(DOWNLOADS_DIR, '*.crdownload'))
            if not crdownloads:
                return sorted(new_zips)

        time.sleep(2)

    # 超时，返回已有的
    all_zips = set()
    for type_info in DOWNLOAD_TYPES.values():
        for pattern in type_info['zip_patterns']:
            all_zips |= set(glob.glob(os.path.join(DOWNLOADS_DIR, pattern)))
    new_zips = all_zips - existing_zips
    if new_zips:
        print(f"  ⚠️ 下载超时（{timeout}秒），使用已有文件")
        return sorted(new_zips)

    print(f"  ⚠️ 下载超时（{timeout}秒），未找到新文件")
    return []


def match_zip_to_type(zip_path, item_code):
    """识别zip文件属于哪种下载类型

    Args:
        zip_path: zip文件路径
        item_code: Item Code（用于校验归属）

    Returns:
        (type_key, is_match) 或 (None, False)
    """
    basename = os.path.basename(zip_path)

    # 校验Item Code
    is_match = item_code is None or item_code in basename

    # 识别类型：先匹配更具体的模式
    if 'Retail_Ready' in basename or 'retail_ready' in basename.lower():
        if 'information' in basename.lower() or 'Information' in basename:
            return 'information', is_match
        return 'retail_ready', is_match

    if 'information' in basename.lower() or 'Information' in basename:
        return 'information', is_match

    if 'image+file' in basename.lower() or 'Image+File' in basename:
        return 'to_b', is_match

    return None, is_match


def process_zip(zip_path, output_dir, item_code, sub_dir=None):
    """处理单个zip文件：移动、解压、统计

    Args:
        zip_path: zip文件路径
        output_dir: 输出目录
        item_code: Item Code
        sub_dir: 子目录名（如 'To_B', 'Retail_Ready'），避免不同类型素材解压到同一目录导致重复

    Returns:
        dict: {'success': bool, 'image_count': int, 'file': str, 'type_key': str}
    """
    basename = os.path.basename(zip_path)
    type_key, is_match = match_zip_to_type(zip_path, item_code)
    label = DOWNLOAD_TYPES[type_key]['label'] if type_key else '未知类型'

    if not is_match:
        print(f"  ⚠️ 文件不匹配当前Item Code: {basename}")
        label = f'{label}（⚠️ Item Code不匹配）'

    print(f"  📦 处理: {basename} → [{label}] sub_dir={sub_dir}")

    # 解压目标目录：如果有sub_dir则解压到子目录，避免不同类型素材重复
    extract_dir = os.path.join(output_dir, sub_dir) if sub_dir else output_dir
    print(f"  📂 解压到: {extract_dir}")
    os.makedirs(extract_dir, exist_ok=True)

    # 移动zip到解压目录
    dest = os.path.join(extract_dir, basename)
    if os.path.exists(dest):
        name, ext = os.path.splitext(basename)
        i = 1
        while os.path.exists(dest):
            dest = os.path.join(extract_dir, f"{name}_{i}{ext}")
            i += 1

    shutil.move(zip_path, dest)

    image_count = 0
    success = True

    try:
        with zipfile.ZipFile(dest, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        os.remove(dest)
        print(f"  ✅ 已解压")

        # 统计图片数量（只在当前子目录下统计，避免重复计数）
        images = glob.glob(os.path.join(extract_dir, '**/*.jpg'), recursive=True)
        images += glob.glob(os.path.join(extract_dir, '**/*.png'), recursive=True)
        images += glob.glob(os.path.join(extract_dir, '**/*.jpeg'), recursive=True)
        image_count = len(images)
    except zipfile.BadZipFile:
        print(f"  ❌ 素材包损坏，无法解压")
        success = False

    return {
        'success': success,
        'image_count': image_count,
        'file': basename,
        'type_key': type_key,
    }


def download_materials(product_id, output_dir, extract=True, download_types=None, skip_navigate=False):
    """下载素材包

    流程：
    1. 打开页面
    2. 记录existing_zips
    3. 点击下载按钮
    4. 检测弹出框选项
    5. 如果有弹出框：逐个点击选项，每次重新打开页面
    6. 如果没有弹出框（普通产品）：直接等待下载
    7. 每次点击可能下载多个zip，等待所有下载完成

    Args:
        product_id: 商品ID
        output_dir: 输出目录
        extract: 是否解压
        download_types: 未使用（保留兼容）
        skip_navigate: 是否跳过页面导航（调用方已打开页面时设为True）

    Returns:
        dict: {type_key: {'success': bool, 'image_count': int, 'file': str}}
    """
    # 导航到商品页面（如果调用方已导航则跳过）
    if not skip_navigate:
        navigate_to_product(product_id)
        time.sleep(1)

    # 获取Item Code
    item_code = get_item_code_from_page()
    if item_code:
        print(f"  🏷️ Item Code: {item_code}")

    # ★ 关键修复：先记录existing_zips，再点击下载按钮
    existing_zips = set(glob.glob(os.path.join(DOWNLOADS_DIR, '*.zip')))

    # 点击下载按钮
    clicked = click_download_button()
    if not clicked:
        print(f"  ⚠️ 未找到下载按钮")
        return {}

    time.sleep(1.5)

    # 检测弹出框选项
    options = get_popup_options()

    results = {}

    if not options:
        # 普通产品：点击下载按钮后直接开始下载，无需选择
        print(f"  ℹ️ 普通产品，直接下载素材包")

        new_zips = wait_for_downloads(timeout=120, existing_zips=existing_zips)

        if not new_zips:
            # 尝试通过Item Code查找
            if item_code:
                print(f"  🔍 尝试通过Item Code匹配...")
                patterns = [
                    os.path.join(DOWNLOADS_DIR, f'*{item_code}*.zip'),
                ]
                for p in patterns:
                    matches = set(glob.glob(p))
                    new_matches = list(matches - existing_zips)
                    if new_matches:
                        new_zips = new_matches
                        break

        if not new_zips:
            print(f"  ⚠️ 未找到下载的素材包")
            return {}

        # 处理所有新zip（普通产品，按类型解压到不同子目录）
        for zip_path in new_zips:
            # 根据zip类型确定子目录名
            type_key_check, _ = match_zip_to_type(zip_path, item_code)
            if type_key_check == 'information':
                sub_dir = 'Information'
            elif type_key_check == 'to_b':
                sub_dir = 'To_B'
            elif type_key_check == 'retail_ready':
                sub_dir = 'Retail_Ready'
            else:
                sub_dir = None

            if extract:
                result = process_zip(zip_path, output_dir, item_code, sub_dir=sub_dir)
            else:
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, os.path.basename(zip_path))
                shutil.move(zip_path, dest)
                result = {'success': True, 'image_count': 0, 'file': os.path.basename(zip_path)}
            type_key = result.get('type_key', 'unknown')
            results[type_key] = result
    else:
        # 有弹出框：只点击第一个选项（每个选项点击后会同时下载image+file和information两个zip）
        print(f"  📋 检测到 {len(options)} 个下载选项: {', '.join(options)}")
        print(f"  📥 选择: {options[0]}")

        # 直接点击第一个选项
        success = click_popup_option(options[0])
        if not success:
            print(f"  ❌ 点击 {options[0]} 失败")
            return results

        # 等待下载完成（可能下载多个zip）
        new_zips = wait_for_downloads(timeout=120, existing_zips=existing_zips)

        if not new_zips:
            # 尝试通过Item Code查找
            if item_code:
                print(f"  🔍 尝试通过Item Code匹配...")
                patterns = [os.path.join(DOWNLOADS_DIR, f'*{item_code}*.zip')]
                for p in patterns:
                    matches = set(glob.glob(p))
                    new_matches = list(matches - existing_zips)
                    if new_matches:
                        new_zips = [new_matches[0]]
                        break

        if not new_zips:
            print(f"  ❌ {options[0]} 下载失败")
            return results

        # 处理所有新zip（按类型解压到子目录）
        for zip_path in new_zips:
            # 根据zip类型确定子目录名
            type_key_check, _ = match_zip_to_type(zip_path, item_code)
            
            if type_key_check == 'information':
                sub_dir_name = 'Information'
            elif 'Retail' in options[0]:
                sub_dir_name = 'Retail_Ready'
            elif 'To B' in options[0]:
                sub_dir_name = 'To_B'
            else:
                sub_dir_name = options[0].replace(' ', '_')

            if extract:
                result = process_zip(zip_path, output_dir, item_code, sub_dir=sub_dir_name)
            else:
                os.makedirs(output_dir, exist_ok=True)
                dest = os.path.join(output_dir, os.path.basename(zip_path))
                shutil.move(zip_path, dest)
                result = {'success': True, 'image_count': 0, 'file': os.path.basename(zip_path)}
            type_key = result.get('type_key', 'unknown')
            results[type_key] = result

    # 汇总
    total_images = sum(r.get('image_count', 0) for r in results.values() if r.get('success'))
    print(f"\n  📊 下载汇总:")
    for dtype, r in results.items():
        status = '✅' if r.get('success') else '❌'
        label = DOWNLOAD_TYPES.get(dtype, {}).get('label', dtype)
        print(f"    {status} {label}: {r.get('image_count', 0)}张图片 ({r.get('file', '')})")
    print(f"    总计: {total_images}张图片")

    return results


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  download_materials.py <product_id> [选项]")
        print("")
        print("选项:")
        print("  --output-dir <dir>        输出目录")
        print("  --no-extract              不解压")
        print("")
        print("说明:")
        print("  脚本会自动检测弹出框中的所有下载选项，逐个下载")
        print("  每次点击选项可能下载多个zip（image+file + information）")
        print("  所有素材包解压到同一个商品文件夹")
        sys.exit(1)

    product_id = sys.argv[1]
    output_dir = f"/Users/jiyuhang/Documents/F/亚马逊工作目录/亚马逊商品/{product_id}"
    extract = True

    # 解析参数
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--output-dir' and i + 1 < len(sys.argv):
            output_dir = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--no-extract':
            extract = False
            i += 1
        else:
            i += 1

    results = download_materials(product_id, output_dir, extract)

    # 返回码：至少一个成功就返回0
    any_success = any(r['success'] for r in results.values()) if results else False
    sys.exit(0 if any_success else 1)


if __name__ == '__main__':
    main()
