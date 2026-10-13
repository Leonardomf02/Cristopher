// Reminders da Apple pelo EventKit. Uso: reminders dump | reminders apply < ops.json
//
// Porque não AppleScript: ler os 251 reminders dele leva 37s e cada escrita ~8s,
// porque cada propriedade é um Apple Event para a app do Reminders. Pelo EventKit
// a mesma leitura leva 0,6s e as escritas são todas numa transacção.
import EventKit
import Foundation

let iso: DateFormatter = {
    let f = DateFormatter()
    // Com o fuso explícito: do outro lado o SQLite grava em UTC e as datas da
    // Apple são locais — sem isto, uma hora de diferença decidia quem ganhava
    // um conflito.
    f.dateFormat = "yyyy-MM-dd'T'HH:mm:ssXXXXX"
    f.locale = Locale(identifier: "en_US_POSIX")
    return f
}()

func morre(_ msg: String, _ codigo: Int32 = 1) -> Never {
    let saida = ["ok": false, "error": msg] as [String: Any]
    if let d = try? JSONSerialization.data(withJSONObject: saida) {
        FileHandle.standardOutput.write(d)
    }
    exit(codigo)
}

func escreve(_ obj: [String: Any]) {
    guard let d = try? JSONSerialization.data(withJSONObject: obj) else { morre("json") }
    FileHandle.standardOutput.write(d)
}

let store = EKEventStore()

func pedeAcesso() {
    let sem = DispatchSemaphore(value: 0)
    var concedido = false
    var erro: Error?
    store.requestFullAccessToReminders { ok, e in
        concedido = ok
        erro = e
        sem.signal()
    }
    sem.wait()
    if !concedido {
        // O erro é o que distingue "disse que não" de "nem chegou a perguntar"
        // (processo sem interface, que é o caso do backend a correr em launchd).
        morre("sem acesso aos Reminders\(erro.map { ": \($0.localizedDescription)" } ?? "")", 2)
    }
}

func hexDaCor(_ cal: EKCalendar) -> String {
    guard let cor = cal.cgColor, let comps = cor.components, comps.count >= 3 else { return "#3B82F6" }
    let r = Int((comps[0] * 255).rounded()), g = Int((comps[1] * 255).rounded()), b = Int((comps[2] * 255).rounded())
    return String(format: "#%02X%02X%02X", max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
}

func todos(_ cals: [EKCalendar]) -> [EKReminder] {
    let sem = DispatchSemaphore(value: 0)
    var out: [EKReminder] = []
    store.fetchReminders(matching: store.predicateForReminders(in: cals)) { rems in
        out = rems ?? []
        sem.signal()
    }
    sem.wait()
    return out
}

func serializa(_ r: EKReminder) -> [String: Any] {
    var o: [String: Any] = [
        "id": r.calendarItemIdentifier,
        "list": r.calendar?.calendarIdentifier ?? "",
        "title": r.title ?? "",
        "notes": r.notes ?? "",
        "completed": r.isCompleted,
        "priority": r.priority,
    ]
    if let d = r.completionDate { o["completed_at"] = iso.string(from: d) }
    if let d = r.lastModifiedDate { o["modified"] = iso.string(from: d) }
    if let d = r.creationDate { o["created"] = iso.string(from: d) }
    if let c = r.dueDateComponents {
        if let y = c.year, let m = c.month, let d = c.day {
            o["due_date"] = String(format: "%04d-%02d-%02d", y, m, d)
            // Sem hora, o reminder é "para aquele dia" — é a distinção que o
            // Cristopher guarda em due_time nulo.
            if let h = c.hour, let mi = c.minute {
                o["due_time"] = String(format: "%02d:%02d", h, mi)
            }
        }
    }
    return o
}

// ── dump ─────────────────────────────────────────────────────────

func dump() {
    let cals = store.calendars(for: .reminder)
    let listas = cals.map { ["id": $0.calendarIdentifier, "name": $0.title, "color": hexDaCor($0),
                             "readonly": !$0.allowsContentModifications] as [String: Any] }
    escreve(["ok": true, "lists": listas, "reminders": todos(cals).map(serializa)])
}

// ── apply ────────────────────────────────────────────────────────

func componentes(_ data: String?, _ hora: String?) -> DateComponents? {
    guard let data = data else { return nil }
    let p = data.split(separator: "-").compactMap { Int($0) }
    guard p.count == 3 else { return nil }
    var c = DateComponents()
    c.year = p[0]; c.month = p[1]; c.day = p[2]
    if let hora = hora {
        let h = hora.split(separator: ":").compactMap { Int($0) }
        if h.count >= 2 { c.hour = h[0]; c.minute = h[1] }
    }
    c.timeZone = TimeZone.current
    return c
}

func preenche(_ r: EKReminder, _ campos: [String: Any]) {
    if let t = campos["title"] as? String { r.title = t }
    if let n = campos["notes"] as? String { r.notes = n.isEmpty ? nil : n }
    if let p = campos["priority"] as? Int { r.priority = p }
    if let c = campos["completed"] as? Bool {
        // isCompleted = false limpa a completionDate sozinho; pôr a data à mão
        // é o que faz um item "por fazer" aparecer feito no iPhone.
        r.isCompleted = c
    }
    let novas = componentes(campos["due_date"] as? String, campos["due_time"] as? String)
    if r.dueDateComponents != novas {
        r.dueDateComponents = novas
        for a in r.alarms ?? [] { r.removeAlarm(a) }
        // Um reminder sem alarme não toca no telemóvel. Só se põe alarme no que
        // ainda está para vir: pôr nos atrasados era despejar notificações de
        // coisas de 2024 na primeira sincronização.
        if let novas = novas, novas.hour != nil,
           let quando = Calendar.current.date(from: novas), quando > Date() {
            r.addAlarm(EKAlarm(absoluteDate: quando))
        }
    }
}

func apply() {
    guard let entrada = try? FileHandle.standardInput.readToEnd(),
          let ops = try? JSONSerialization.jsonObject(with: entrada) as? [String: Any] else {
        morre("stdin não é json")
    }

    var erros: [String] = []
    var listasNovas: [String: String] = [:]
    var criados: [String: String] = [:]
    var actualizados = 0, apagados = 0
    var renomeadas: [String] = [], listasApagadas: [String] = []

    let cals = store.calendars(for: .reminder)
    var porId = Dictionary(cals.map { ($0.calendarIdentifier, $0) }, uniquingKeysWith: { a, _ in a })

    for l in ops["create_lists"] as? [[String: Any]] ?? [] {
        let ref = l["ref"] as? String ?? ""
        guard let fonte = store.defaultCalendarForNewReminders()?.source else {
            erros.append("lista \(ref): não há conta onde criar")
            continue
        }
        let cal = EKCalendar(for: .reminder, eventStore: store)
        cal.title = l["name"] as? String ?? "Cristopher"
        cal.source = fonte
        do {
            try store.saveCalendar(cal, commit: true)
            listasNovas[ref] = cal.calendarIdentifier
            porId[cal.calendarIdentifier] = cal
        } catch { erros.append("lista \(ref): \(error.localizedDescription)") }
    }

    for l in ops["update_lists"] as? [[String: Any]] ?? [] {
        guard let id = l["id"] as? String, let nome = l["name"] as? String else { continue }
        guard let cal = porId[id] else { erros.append("renomear lista \(id): já não existe"); continue }
        cal.title = nome
        do {
            try store.saveCalendar(cal, commit: true)
            renomeadas.append(id)
        } catch { erros.append("renomear lista \(id): \(error.localizedDescription)") }
    }

    func calendario(_ chave: String?) -> EKCalendar? {
        guard let chave = chave else { return store.defaultCalendarForNewReminders() }
        if let c = porId[chave] { return c }
        if chave.hasPrefix("ref:"), let id = listasNovas[String(chave.dropFirst(4))] { return porId[id] }
        return store.defaultCalendarForNewReminders()
    }

    for c in ops["create"] as? [[String: Any]] ?? [] {
        let ref = c["ref"] as? String ?? ""
        guard let cal = calendario(c["list"] as? String) else {
            erros.append("criar \(ref): sem lista")
            continue
        }
        let r = EKReminder(eventStore: store)
        r.calendar = cal
        preenche(r, c)
        do {
            try store.save(r, commit: false)
            criados[ref] = r.calendarItemIdentifier
        } catch { erros.append("criar \(ref): \(error.localizedDescription)") }
    }

    for u in ops["update"] as? [[String: Any]] ?? [] {
        guard let id = u["id"] as? String else { continue }
        guard let r = store.calendarItem(withIdentifier: id) as? EKReminder else {
            erros.append("actualizar \(id): já não existe")
            continue
        }
        if let destino = u["list"] as? String, let cal = calendario(destino), cal != r.calendar {
            r.calendar = cal
        }
        preenche(r, u)
        do {
            try store.save(r, commit: false)
            actualizados += 1
        } catch { erros.append("actualizar \(id): \(error.localizedDescription)") }
    }

    for id in ops["delete"] as? [String] ?? [] {
        guard let r = store.calendarItem(withIdentifier: id) as? EKReminder else { continue }
        do {
            try store.remove(r, commit: false)
            apagados += 1
        } catch { erros.append("apagar \(id): \(error.localizedDescription)") }
    }

    do { try store.commit() } catch { morre("commit falhou: \(error.localizedDescription)") }

    // Depois dos reminders: apagar a lista leva os que ainda lá estejam.
    for id in ops["delete_lists"] as? [String] ?? [] {
        guard let cal = porId[id] else { listasApagadas.append(id); continue }
        do {
            try store.removeCalendar(cal, commit: true)
            listasApagadas.append(id)
        } catch { erros.append("apagar lista \(id): \(error.localizedDescription)") }
    }

    escreve(["ok": true, "lists": listasNovas, "created": criados,
             "updated": actualizados, "deleted": apagados, "errors": erros,
             "renamed_lists": renomeadas, "deleted_lists": listasApagadas])
}

// ── main ─────────────────────────────────────────────────────────

let comando = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "dump"
pedeAcesso()
switch comando {
case "dump": dump()
case "apply": apply()
default: morre("comando desconhecido: \(comando)")
}
