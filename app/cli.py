"""Explicit bootstrap only: never inserts demo data at server startup."""
import argparse
import getpass
import json
from datetime import datetime, timedelta, timezone
from .db import audit, connect, encode, initialize, now, password_hash


def bootstrap(demo=False):
    initialize()
    with connect(True) as db:
        if db.execute('SELECT 1 FROM users').fetchone():
            raise SystemExit('数据库已有账号，禁止重复初始化。')
        password = getpass.getpass('设置管理员密码（至少12位）：')
        if len(password) < 12:
            raise SystemExit('密码至少12位。')
        if password != getpass.getpass('再次输入：'):
            raise SystemExit('两次密码不一致。')
        db.execute('INSERT INTO users(username,name,password,role,store,job,stations) VALUES(?,?,?,?,?,?,?)',
                   ('admin', '主管', password_hash(password), 'admin', 'pilot', 'bartender', encode(['main', 'terrace'])))
        if demo:
            # Deliberately no public default passwords; operator sets staff password too.
            staff_password = getpass.getpass('设置演示员工 staff 密码（至少12位）：')
            if len(staff_password) < 12:
                raise SystemExit('密码至少12位。')
            db.execute('INSERT INTO users(username,name,password,role,store,job,stations) VALUES(?,?,?,?,?,?,?)',
                       ('staff', '演示新人', password_hash(staff_password), 'staff', 'pilot', 'bartender', encode(['main'])))
            seed(db)
    print('初始化完成。使用 admin 登录。' + ('演示员工：staff。内容仅供功能演示。' if demo else '未添加任何示例知识。'))


def seed(db):
    items = [
        ('金汤力', 'recipe', ['Gin Tonic', 'Gin and Tonic', 'G&T'], {
            'summary': '演示配方，未经合作酒吧确认，不可直接作为门店出品标准。',
            'ingredients': [{'name': '金酒', 'amount': '45', 'unit': 'ml'}, {'name': '汤力水', 'amount': '120', 'unit': 'ml'}],
            'technique': '兑和', 'glass': '高球杯', 'garnish': '青柠片', 'allergens': ['须按实际原料标签复核'],
            'steps': ['核对门店已批准的实际配方。', '按卡片计量，完成后由带教师傅检查。']}),
        ('开吧检查', 'sop', ['开吧', '开店', '营业准备'], {
            'summary': '演示检查清单。正式流程须由门店负责人审核。', 'ingredients': [],
            'technique': '', 'glass': '', 'garnish': '', 'allergens': [],
            'steps': ['与当班主管确认当日活动和有效酒单。', '按门店标准检查工具、杯具及工作台。', '发现异常先记录并联系主管，未确认前不要使用相关设备。']}),
        ('服务交接', 'sop', ['交接班', '交接'], {
            'summary': '演示服务交接流程。', 'ingredients': [], 'technique': '', 'glass': '', 'garnish': '', 'allergens': [],
            'steps': ['确认未完成事项和负责人。', '核对已发布的规则变更。', '双方确认交接记录。']})]
    revision_ids = []
    for title, kind, aliases, content in items:
        did = db.execute('INSERT INTO documents(store,title,kind,jobs,stations,aliases,risk) VALUES(?,?,?,?,?,?,0)',
                         ('pilot', title, kind, encode(['bartender']), encode(['main', 'terrace']), encode(aliases))).lastrowid
        rid = db.execute('INSERT INTO revisions(document_id,version,state,content,source,effective_at,created_by,approved_by,approved_at) VALUES(?,1,?,?,?,?,1,1,?)',
                         (did, 'published', encode(content), 'BarOS 功能演示资料，非真实门店标准', now(), now())).lastrowid
        revision_ids.append(rid)
    mid = db.execute('INSERT INTO modules(store,title,objective,revision_ids,quiz,pass_score,created_by) VALUES(?,?,?,?,?,100,1)',
                     ('pilot', '第一班：开吧与标准查询', '学会查找当前有效标准，并在无法确认时向主管求助。', encode([revision_ids[1]]),
                      encode([{'question': '没有找到已审核标准时应该怎么做？', 'options': ['凭经验猜测', '咨询当班主管'], 'answer': 1}]))).lastrowid
    db.execute('INSERT INTO assignments(module_id,user_id,assigned_by) VALUES(?,2,1)', (mid,))
    audit(db, {'id': 1, 'store': 'pilot'}, 'demo_seeded', 'explicit-demo-only')


def cleanup(days):
    if days < 1:
        raise SystemExit('保留天数须大于零。')
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec='seconds')
    with connect(True) as db:
        eligible = 'SELECT id FROM queries WHERE created_at<? AND id NOT IN (SELECT query_id FROM escalations) AND id NOT IN (SELECT f.query_id FROM feedback f JOIN knowledge_proposals p ON p.feedback_id=f.id)'
        db.execute('DELETE FROM feedback WHERE query_id IN ('+eligible+')', (cutoff,))
        count = db.execute('DELETE FROM queries WHERE id IN ('+eligible+')', (cutoff,)).rowcount
        db.execute('DELETE FROM sessions WHERE expires<=?', (now(),))
        db.execute('DELETE FROM login_limits WHERE reset<?', (datetime.now(timezone.utc).timestamp(),))
    print(f'已清理 {count} 条过期查询记录及其反馈；培训与审计记录保留。')


def main():
    parser = argparse.ArgumentParser(description='BarOS 初始化与保留期限维护')
    parser.add_argument('command', choices=['init', 'demo', 'cleanup', 'backup', 'restore'])
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--destination', help='备份或恢复的全新目标文件；禁止覆盖已有文件')
    parser.add_argument('--source', help='restore使用的备份文件')
    args = parser.parse_args()
    if args.command in ('backup', 'restore'):
        if not args.destination or (args.command == 'restore' and not args.source):
            parser.error('backup需要--destination；restore需要--source和--destination')
        from .dbtools import backup, snapshot
        try:
            target = backup(args.destination) if args.command == 'backup' else snapshot(args.source, args.destination)
        except (OSError, ValueError) as exc:
            raise SystemExit(str(exc))
        print(f'完整性验证通过：{target}。恢复到新路径后，请先验证数据再手动切换 BAROS_DB。')
        return
    if args.command == 'cleanup':
        initialize()
        cleanup(args.days)
    else:
        bootstrap(args.command == 'demo')


if __name__ == '__main__':
    main()
