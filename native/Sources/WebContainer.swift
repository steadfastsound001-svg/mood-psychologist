import SwiftUI
import WebKit
import AuthenticationServices

#if os(iOS)
import UIKit
typealias PlatformView = UIView
#elseif os(macOS)
import AppKit
typealias PlatformView = NSView
#endif

// realистичный Safari-UA: без него Google OAuth в WKWebView ловит "disallowed_useragent".
#if os(iOS)
private let kUserAgent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
#else
private let kUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
#endif

/// общий конструктор webview + конфиг (хаптики, медиа, UA).
func makeWebView(coordinator: WebCoordinator) -> WKWebView {
    let cfg = WKWebViewConfiguration()
    #if os(iOS)
    cfg.allowsInlineMediaPlayback = true                // iOS-only ключи
    cfg.mediaTypesRequiringUserActionForPlayback = []   // голосовые без лишнего тапа
    #endif

    let ucc = WKUserContentController()
    for name in ["haptic", "hapticSel", "hapticOk"] {
        ucc.add(coordinator, name: name)                // мост JS → CoreHaptics
    }
    cfg.userContentController = ucc

    let web = WKWebView(frame: .zero, configuration: cfg)
    web.customUserAgent = kUserAgent
    web.navigationDelegate = coordinator
    web.uiDelegate = coordinator
    coordinator.webView = web                           // для перезагрузки после google-входа
    web.allowsBackForwardNavigationGestures = true
    if #available(iOS 16.4, macOS 13.3, *) { web.isInspectable = true }   // Web Inspector в дебаге

    #if os(iOS)
    web.scrollView.bounces = false                      // без резинового оверскролла
    web.scrollView.contentInsetAdjustmentBehavior = .never
    web.scrollView.showsVerticalScrollIndicator = false
    web.isOpaque = false
    web.backgroundColor = .clear
    web.scrollView.backgroundColor = .clear
    #else
    web.setValue(false, forKey: "drawsBackground")      // прозрачный фон на macOS
    #endif
    return web
}

// ───────── представление для SwiftUI (две платформы) ─────────

#if os(iOS)
struct WebContainer: UIViewRepresentable {
    let url: URL
    func makeCoordinator() -> WebCoordinator { WebCoordinator() }
    func makeUIView(context: Context) -> WKWebView {
        let web = makeWebView(coordinator: context.coordinator)
        web.load(URLRequest(url: url))
        return web
    }
    func updateUIView(_ web: WKWebView, context: Context) {}
}
#elseif os(macOS)
struct WebContainer: NSViewRepresentable {
    let url: URL
    func makeCoordinator() -> WebCoordinator { WebCoordinator() }
    func makeNSView(context: Context) -> WKWebView {
        let web = makeWebView(coordinator: context.coordinator)
        web.load(URLRequest(url: url))
        return web
    }
    func updateNSView(_ web: WKWebView, context: Context) {}
}
#endif

// ───────── координатор: хаптики + навигация + JS-диалоги ─────────

final class WebCoordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate,
                            ASWebAuthenticationPresentationContextProviding {

    weak var webView: WKWebView?
    private var authSession: ASWebAuthenticationSession?

    // JS → нативная тактилка
    func userContentController(_ ucc: WKUserContentController, didReceive msg: WKScriptMessage) {
        switch msg.name {
        case "haptic":    impact(String(describing: msg.body))
        case "hapticSel": selection()
        case "hapticOk":  success()
        default: break
        }
    }

    #if os(iOS)
    private func impact(_ kind: String) {
        let style: UIImpactFeedbackGenerator.FeedbackStyle =
            kind == "heavy" ? .heavy : kind == "medium" ? .medium : .light
        let g = UIImpactFeedbackGenerator(style: style); g.prepare(); g.impactOccurred()
    }
    private func selection() { let g = UISelectionFeedbackGenerator(); g.prepare(); g.selectionChanged() }
    private func success()   { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    #else
    private func haptic(_ p: NSHapticFeedbackManager.FeedbackPattern) {
        NSHapticFeedbackManager.defaultPerformer.perform(p, performanceTime: .now)
    }
    private func impact(_ kind: String) { haptic(kind == "light" ? .alignment : .generic) }
    private func selection() { haptic(.alignment) }
    private func success()   { haptic(.levelChange) }
    #endif

    // внешние ссылки (tel/mailto/новое окно на чужой домен) → системный браузер.
    // google oauth и переходы внутри нашего домена остаются в webview.
    func webView(_ web: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let u = action.request.url {
            // google-вход → системный браузер (ASWebAuthenticationSession), не в webview
            if u.path == "/api/auth/google", (u.query?.contains("app=1") != true),
               let scheme = u.scheme, let host = u.host {
                startGoogleAuth(base: "\(scheme)://\(host)")
                decisionHandler(.cancel); return
            }
            if let s = u.scheme?.lowercased(), ["tel", "mailto", "facetime", "sms"].contains(s) {
                openExternal(u); decisionHandler(.cancel); return
            }
        }
        decisionHandler(.allow)
    }

    // ── google-вход через системный Safari-шит; токен возвращается на soulauth:// ──
    private func startGoogleAuth(base: String) {
        guard let authURL = URL(string: base + "/api/auth/google?app=1") else { return }
        let session = ASWebAuthenticationSession(url: authURL, callbackURLScheme: "soulauth") { [weak self] cb, _ in
            guard let self = self, let cb = cb else { return }   // отмена/ошибка — остаёмся на входе
            let items = URLComponents(url: cb, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let token = items.first { $0.name == "token" }?.value
            let onb = items.first { $0.name == "onb" }?.value ?? "0"
            if let token = token, !token.isEmpty {
                var comps = URLComponents(string: base + "/")
                comps?.queryItems = [URLQueryItem(name: "token", value: token),
                                     URLQueryItem(name: "onb", value: onb)]
                if let target = comps?.url { self.webView?.load(URLRequest(url: target)) }
            } else if let home = URL(string: base) {
                self.webView?.load(URLRequest(url: home))        // auth_error → назад на вход
            }
        }
        session.presentationContextProvider = self
        // prefersEphemeralWebSession по умолчанию false → cookie делятся с Safari, google не режет
        authSession = session
        session.start()
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        #if os(iOS)
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        return scenes.flatMap { $0.windows }.first { $0.isKeyWindow } ?? ASPresentationAnchor()
        #else
        return webView?.window ?? NSApplication.shared.windows.first ?? ASPresentationAnchor()
        #endif
    }

    // target=_blank / window.open → если нет целевого фрейма, открыть снаружи
    func webView(_ web: WKWebView, createWebViewWith cfg: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = action.request.url { openExternal(u) }
        return nil
    }

    private func openExternal(_ u: URL) {
        #if os(iOS)
        UIApplication.shared.open(u)
        #else
        NSWorkspace.shared.open(u)
        #endif
    }

    // ── JS alert/confirm/prompt: WKWebView их не показывает сам ──
    func webView(_ web: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        present(title: message, confirm: false) { _ in completionHandler() }
    }
    func webView(_ web: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        present(title: message, confirm: true) { ok in completionHandler(ok) }
    }
    func webView(_ web: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        presentInput(prompt: prompt, defaultText: defaultText ?? "") { completionHandler($0) }
    }

    #if os(iOS)
    private func topVC() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        var vc = scenes.flatMap { $0.windows }.first { $0.isKeyWindow }?.rootViewController
        while let p = vc?.presentedViewController { vc = p }
        return vc
    }
    private func present(title: String, confirm: Bool, done: @escaping (Bool) -> Void) {
        let a = UIAlertController(title: nil, message: title, preferredStyle: .alert)
        if confirm { a.addAction(UIAlertAction(title: "отмена", style: .cancel) { _ in done(false) }) }
        a.addAction(UIAlertAction(title: "ок", style: .default) { _ in done(true) })
        topVC()?.present(a, animated: true)
    }
    private func presentInput(prompt: String, defaultText: String, done: @escaping (String?) -> Void) {
        let a = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
        a.addTextField { $0.text = defaultText }
        a.addAction(UIAlertAction(title: "отмена", style: .cancel) { _ in done(nil) })
        a.addAction(UIAlertAction(title: "ок", style: .default) { _ in done(a.textFields?.first?.text) })
        topVC()?.present(a, animated: true)
    }
    #else
    private func present(title: String, confirm: Bool, done: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = title
        a.addButton(withTitle: "ок"); if confirm { a.addButton(withTitle: "отмена") }
        done(a.runModal() == .alertFirstButtonReturn)
    }
    private func presentInput(prompt: String, defaultText: String, done: @escaping (String?) -> Void) {
        let a = NSAlert(); a.messageText = prompt; a.addButton(withTitle: "ок"); a.addButton(withTitle: "отмена")
        let tf = NSTextField(frame: NSRect(x: 0, y: 0, width: 240, height: 24)); tf.stringValue = defaultText
        a.accessoryView = tf
        done(a.runModal() == .alertFirstButtonReturn ? tf.stringValue : nil)
    }
    #endif
}
