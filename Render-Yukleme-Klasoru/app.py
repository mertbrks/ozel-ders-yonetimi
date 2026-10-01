import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from database import init_db, get_db_connection

app = Flask(__name__)
app.secret_key = 'super_gizli_anahtar_degistirilebilir' # Flash mesajları (uyarılar) için gerekli

# Veritabanı tablolarını oluştur (IF NOT EXISTS olduğu için güvenli)
init_db()

@app.route('/')
def index():
    conn = get_db_connection()
    
    # Bugünün derslerini bul
    today_str = datetime.now().strftime('%Y-%m-%d')
    todays_lessons = conn.execute('''
        SELECT l.lesson_date, l.status, s.full_name 
        FROM lessons l
        JOIN students s ON l.student_id = s.id
        WHERE substr(CAST(l.lesson_date AS text), 1, 10) = %s
        ORDER BY l.lesson_date ASC
    ''', (today_str,)).fetchall()
    
    # Bekleyen ödemelerin toplamını hesapla
    pending_payments_row = conn.execute('''
        SELECT SUM(s.hourly_rate) as total_debt 
        FROM lessons l
        JOIN students s ON l.student_id = s.id
        WHERE l.status = 'yapildi' 
        AND l.id NOT IN (SELECT lesson_id FROM payments WHERE is_paid = 1)
    ''').fetchone()
    total_pending = pending_payments_row['total_debt'] if pending_payments_row and pending_payments_row['total_debt'] else 0
    
    # Son 6 ayın gelir istatistikleri (Grafik için)
    import calendar
    chart_labels = []
    chart_data = []
    
    # Son 6 ayı hesapla
    today = datetime.now()
    for i in range(5, -1, -1):
        # i ay öncesi
        m = today.month - i
        y = today.year
        if m <= 0:
            m += 12
            y -= 1
            
        month_str = f"{y}-{m:02d}"
        
        # O ayki yapilmis ve odenmis derslerin toplami
        # Gerçek tahsilatı (payments) baz alalım
        income_row = conn.execute('''
            SELECT SUM(amount) as m_income
            FROM payments
            WHERE is_paid = 1 AND substr(CAST(payment_date AS text), 1, 7) = %s
        ''', (month_str,)).fetchone()
        
        income = income_row['m_income'] if income_row and income_row['m_income'] else 0
        
        # Etiket olarak ay adı
        month_name = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'][m-1]
        chart_labels.append(f"{month_name} {y}")
        chart_data.append(income)
        
    conn.close()
    return render_template('index.html', 
                           todays_lessons=todays_lessons, 
                           total_pending=total_pending,
                           chart_labels=chart_labels,
                           chart_data=chart_data)

@app.route('/students')
def students():
    conn = get_db_connection()
    students_data = conn.execute('SELECT * FROM students ORDER BY full_name').fetchall()
    conn.close()
    return render_template('students.html', students=students_data)

@app.route('/student/<int:id>')
def student_profile(id):
    conn = get_db_connection()
    student = conn.execute('SELECT * FROM students WHERE id = %s', (id,)).fetchone()
    
    if not student:
        flash('Öğrenci bulunamadı.', 'danger')
        return redirect(url_for('students'))
        
    # Öğrencinin geçmiş ve gelecek tüm dersleri
    lessons = conn.execute('''
        SELECT id, lesson_date, status, topic, homework, notes 
        FROM lessons 
        WHERE student_id = %s 
        ORDER BY lesson_date DESC
    ''', (id,)).fetchall()
    
    # Toplam ders, ödenen, ödenmeyen bakiyeler vb.
    stats = conn.execute('''
        SELECT 
            COUNT(id) as total_lessons,
            SUM(CASE WHEN status = 'yapildi' THEN 1 ELSE 0 END) as done_lessons
        FROM lessons WHERE student_id = %s
    ''', (id,)).fetchone()
    
    # Bekleyen bakiye hesabı
    unpaid_count = conn.execute('''
        SELECT COUNT(id) as c FROM lessons 
        WHERE student_id = %s AND status = 'yapildi' 
        AND id NOT IN (SELECT lesson_id FROM payments WHERE is_paid = 1)
    ''', (id,)).fetchone()['c']
    
    pending_balance = unpaid_count * student['hourly_rate']
    
    conn.close()
    
    import urllib.parse
    # WhatsApp Mesajı oluşturma (örnek format)
    if pending_balance > 0:
        wa_text = f"Merhaba {student['parent_contact'] or 'Velimiz'}, {student['full_name']} için tamamlanan {unpaid_count} dersin toplam {pending_balance} TL bakiyesi bulunmaktadır. İyi günler dilerim."
    else:
        wa_text = f"Merhaba {student['parent_contact'] or 'Velimiz'}, {student['full_name']} ile bugün dersimizi tamamladık. İyi günler dilerim."
        
    wa_link = f"https://wa.me/?text={urllib.parse.quote(wa_text)}"
    
    return render_template('student_profile.html', student=student, lessons=lessons, stats=stats, pending_balance=pending_balance, wa_link=wa_link)

@app.route('/students/add', methods=['POST'])
def add_student():
    full_name = request.form.get('full_name')
    grade_level = request.form.get('grade_level')
    parent_contact = request.form.get('parent_contact')
    hourly_rate = request.form.get('hourly_rate')
    default_duration = request.form.get('default_duration', 60)
    notes = request.form.get('notes')

    if not full_name or not hourly_rate:
        flash('Ad Soyad ve Ders Ücreti zorunludur.', 'danger')
    else:
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO students (full_name, grade_level, parent_contact, hourly_rate, default_duration, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (full_name, grade_level, parent_contact, hourly_rate, default_duration, notes))
        conn.commit()
        conn.close()
        flash('Öğrenci başarıyla eklendi!', 'success')
        
    return redirect(url_for('students'))

@app.route('/students/edit/<int:id>', methods=['POST'])
def edit_student(id):
    full_name = request.form.get('full_name')
    grade_level = request.form.get('grade_level')
    parent_contact = request.form.get('parent_contact')
    hourly_rate = request.form.get('hourly_rate')
    default_duration = request.form.get('default_duration', 60)
    notes = request.form.get('notes')

    if not full_name or not hourly_rate:
        flash('Ad Soyad ve Ders Ücreti zorunludur.', 'danger')
    else:
        conn = get_db_connection()
        conn.execute('''
            UPDATE students 
            SET full_name = %s, grade_level = %s, parent_contact = %s, hourly_rate = %s, default_duration = %s, notes = %s
            WHERE id = %s
        ''', (full_name, grade_level, parent_contact, hourly_rate, default_duration, notes, id))
        conn.commit()
        conn.close()
        flash('Öğrenci bilgileri güncellendi!', 'success')
        
    return redirect(url_for('students'))

@app.route('/schedule')
def schedule():
    conn = get_db_connection()
    students = conn.execute('SELECT * FROM students ORDER BY full_name').fetchall()
    conn.close()
    return render_template('schedule.html', students=students)

@app.route('/api/lessons')
def api_lessons():
    conn = get_db_connection()
    # SQL ile dersleri ve öğrenci adlarını birleştiriyoruz
    lessons = conn.execute('''
        SELECT l.id, l.lesson_date, l.duration_minutes, l.status, l.topic, l.homework, l.notes, s.full_name 
        FROM lessons l
        JOIN students s ON l.student_id = s.id
    ''').fetchall()
    conn.close()
    
    events = []
    for row in lessons:
        try:
            start_dt = datetime.strptime(row['lesson_date'], '%Y-%m-%dT%H:%M')
            end_dt = start_dt + timedelta(minutes=row['duration_minutes'])
            
            # Duruma göre renk belirleme
            color = '#3788d8' # default blue for 'planlandi'
            if row['status'] == 'yapildi':
                color = '#28a745' # green
            elif row['status'] == 'iptal':
                color = '#dc3545' # red

            events.append({
                'id': row['id'],
                'title': f"{row['full_name']} ({row['status']})",
                'start': start_dt.isoformat(),
                'end': end_dt.isoformat(),
                'color': color,
                'extendedProps': {
                    'status': row['status'],
                    'topic': row['topic'] or '',
                    'homework': row['homework'] or '',
                    'notes': row['notes'] or ''
                }
            })
        except Exception as e:
            continue

    return jsonify(events)

@app.route('/schedule/add', methods=['POST'])
def add_lesson():
    student_id = request.form.get('student_id')
    lesson_date = request.form.get('lesson_date') # Beklenen format: YYYY-MM-DDTHH:MM
    weeks = int(request.form.get('weeks', 1))

    if not student_id or not lesson_date:
        flash('Öğrenci ve Tarih seçimi zorunludur.', 'danger')
        return redirect(url_for('schedule'))

    try:
        start_dt = datetime.strptime(lesson_date, '%Y-%m-%dT%H:%M')
    except ValueError:
        flash('Geçersiz tarih formatı.', 'danger')
        return redirect(url_for('schedule'))

    conn = get_db_connection()
    
    # Öğrencinin varsayılan ders süresini al
    student = conn.execute('SELECT default_duration FROM students WHERE id = %s', (student_id,)).fetchone()
    duration = student['default_duration'] if student else 60
    
    # Hafta sayısı kadar ders oluştur
    added_count = 0
    for i in range(weeks):
        current_start = start_dt + timedelta(weeks=i)
        current_end = current_start + timedelta(minutes=duration)
        
        # Çakışma kontrolü (Basit algoritma)
        # Veritabanındaki tüm dersleri çekip tarih/saat aralıklarına bakıyoruz
        # (SQLite'da datetime işlemleri string bazlı yapıldığı için Python tarafında kontrol etmek daha güvenli)
        existing_lessons = conn.execute("SELECT lesson_date, duration_minutes FROM lessons WHERE status != 'iptal'").fetchall()
        
        conflict = False
        for el in existing_lessons:
            el_start = datetime.strptime(el['lesson_date'], '%Y-%m-%dT%H:%M')
            el_end = el_start + timedelta(minutes=el['duration_minutes'])
            
            # Eğer yeni dersin başlangıcı mevcut dersin bitişinden önceyse 
            # VE yeni dersin bitişi mevcut dersin başlangıcından sonraysa çakışma vardır.
            if current_start < el_end and current_end > el_start:
                conflict = True
                break
                
        if conflict:
            flash(f'{current_start.strftime("%d.%m.%Y %H:%M")} tarihindeki ders başka bir dersle çakışıyor! Eklenemedi.', 'warning')
            continue
            
        # Çakışma yoksa ekle
        conn.execute('''
            INSERT INTO lessons (student_id, lesson_date, duration_minutes, status)
            VALUES (%s, %s, %s, %s)
        ''', (student_id, current_start.strftime('%Y-%m-%dT%H:%M'), duration, 'planlandi'))
        added_count += 1
        
    conn.commit()
    conn.close()
    
    if added_count > 0:
        flash(f'{added_count} adet ders başarıyla takvime eklendi.', 'success')
        
    return redirect(url_for('schedule'))

@app.route('/schedule/update', methods=['POST'])
def update_lesson():
    lesson_id = request.form.get('lesson_id')
    status = request.form.get('status')
    topic = request.form.get('topic')
    homework = request.form.get('homework')
    notes = request.form.get('notes')

    conn = get_db_connection()
    conn.execute('''
        UPDATE lessons
        SET status = %s, topic = %s, homework = %s, notes = %s
        WHERE id = %s
    ''', (status, topic, homework, notes, lesson_id))
    conn.commit()
    conn.close()
    
    flash('Ders bilgileri güncellendi.', 'success')
    return redirect(url_for('schedule'))

@app.route('/payments')
def payments():
    conn = get_db_connection()
    # Yapılmış ve ödenmemiş tüm dersleri getiriyoruz
    unpaid_lessons = conn.execute('''
        SELECT l.id as lesson_id, l.lesson_date, l.topic, s.full_name, s.hourly_rate 
        FROM lessons l
        JOIN students s ON l.student_id = s.id
        WHERE l.status = 'yapildi' 
        AND l.id NOT IN (SELECT lesson_id FROM payments WHERE is_paid = 1)
        ORDER BY l.lesson_date ASC
    ''').fetchall()
    
    # En son ödenen 5 ders (geçmiş ödemeler)
    paid_lessons = conn.execute('''
        SELECT p.id as payment_id, p.payment_date, p.amount, s.full_name, l.lesson_date
        FROM payments p
        JOIN lessons l ON p.lesson_id = l.id
        JOIN students s ON l.student_id = s.id
        WHERE p.is_paid = 1
        ORDER BY p.payment_date DESC LIMIT 15
    ''').fetchall()
    
    conn.close()
    return render_template('payments.html', unpaid_lessons=unpaid_lessons, paid_lessons=paid_lessons)

@app.route('/payments/pay/<int:lesson_id>', methods=['POST'])
def pay_lesson(lesson_id):
    conn = get_db_connection()
    # Dersin ve öğrencinin bilgilerini alarak ne kadar ödeneceğini bul
    lesson = conn.execute('''
        SELECT s.hourly_rate 
        FROM lessons l 
        JOIN students s ON l.student_id = s.id 
        WHERE l.id = %s
    ''', (lesson_id,)).fetchone()
    
    if lesson:
        # Ödemeyi kaydet
        payment_date = datetime.now().strftime('%Y-%m-%dT%H:%M')
        conn.execute('''
            INSERT INTO payments (lesson_id, amount, is_paid, payment_date)
            VALUES (%s, %s, 1, %s)
        ''', (lesson_id, lesson['hourly_rate'], payment_date))
        conn.commit()
        flash('Ödeme başarıyla kaydedildi!', 'success')
    else:
        flash('Ders bulunamadı.', 'danger')
        
    conn.close()
    return redirect(url_for('payments'))

@app.route('/payments/undo/<int:payment_id>', methods=['POST'])
def undo_payment(payment_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM payments WHERE id = %s', (payment_id,))
    conn.commit()
    conn.close()
    flash('Tahsilat işlemi geri alındı (iptal edildi).', 'warning')
    return redirect(url_for('payments'))

@app.route('/resources')
def resources():
    conn = get_db_connection()
    resources_data = conn.execute('SELECT * FROM resources ORDER BY grade_level, title').fetchall()
    conn.close()
    return render_template('resources.html', resources=resources_data)

@app.route('/resources/add', methods=['POST'])
def add_resource():
    title = request.form.get('title')
    url = request.form.get('url')
    grade_level = request.form.get('grade_level')
    notes = request.form.get('notes')

    if not title:
        flash('Kaynak adı zorunludur.', 'danger')
    else:
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO resources (title, url, grade_level, notes)
            VALUES (%s, %s, %s, %s)
        ''', (title, url, grade_level, notes))
        conn.commit()
        conn.close()
        flash('Kaynak başarıyla eklendi.', 'success')
        
    return redirect(url_for('resources'))

if __name__ == '__main__':
    # Bütün cihazlardan (ağ içi) erişim için host='0.0.0.0'
    app.run(host='0.0.0.0', port=5000, debug=True)

