import SwiftUI

// точка входа. одно окно на весь webapp.
@main
struct SoulApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                #if os(macOS)
                .frame(minWidth: 420, idealWidth: 480, maxWidth: 900,
                       minHeight: 640, idealHeight: 860, maxHeight: .infinity)
                #endif
        }
        #if os(macOS)
        .windowResizability(.contentSize)
        .defaultSize(width: 480, height: 860)
        #endif
    }
}

struct ContentView: View {
    // прод-адрес webapp. меняешь деплой — меняешь тут.
    static let appURL = URL(string: "https://moodmind-32at.onrender.com")!

    var body: some View {
        WebContainer(url: Self.appURL)
            .ignoresSafeArea()                 // webapp сам рулит safe-area (env(safe-area-inset-*))
            .background(Color(red: 0.055, green: 0.059, blue: 0.071))  // под цвет --page-bg, без белой вспышки
    }
}
