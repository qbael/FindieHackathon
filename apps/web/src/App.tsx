import { useEffect, useState, type ReactNode } from "react";
import { loadUser, logout, type UserProfile } from "./lib/auth";
import { useAction } from "./hooks/hooks";
import { Breadcrumb, EmptyState, ErrorNotice, Icon, Loading } from "./components/ui";
import SignIn from "./pages/SignIn";
import Profile from "./pages/Profile";
import { Intakes, IntakeDetail } from "./pages/Intakes";
import { CustodyHistory, ReturnItem } from "./pages/Custody";
import { Home, Search, ItemDetail, Points, type SearchInput } from "./pages/Explore";
import { PostItem, ReviewImages } from "./pages/Posting";
import {
  ClaimItem,
  Requests,
  ClaimDetail,
  MyPosts,
  TransferItem,
  Messages,
} from "./pages/Recovery";

export default function App() {
  const [path, setPath] = useState(() => window.location.pathname.replace(/\/$/, "") || "/");
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(path !== "/signin");
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [imageSearch, setImageSearch] = useState<SearchInput | null>(null);
  const action = useAction();
  useEffect(() => {
    const navigate = () => {
      const nextPath = window.location.pathname.replace(/\/$/, "") || "/";
      if (nextPath === path) return;
      setLoading(true);
      setPath(nextPath);
    };
    window.addEventListener("popstate", navigate);
    return () => window.removeEventListener("popstate", navigate);
  }, [path]);
  useEffect(() => {
    if (path === "/signin") return;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    let active = true;
    setLoading(true);
    setError(null);
    loadUser(controller.signal)
      .then((value) => {
        if (active) setUser(value);
      })
      .catch(() => {
        if (active)
          setError(
            new Error(
              "Chưa kiểm tra được phiên đăng nhập. Hãy kiểm tra kết nối và thử lại.",
            ),
          );
      })
      .finally(() => {
        clearTimeout(timeout);
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt, path]);

  const itemRoute = path.match(
    /^\/items\/([\da-f-]{36})(?:\/(claim|review|transfer|edit|history|return))?$/i,
  );
  const claimRoute = path.match(/^\/claims\/([\da-f-]{36})$/i);
  const intakeRoute = path.match(/^\/intakes\/([\da-f-]{36})$/i);
  const titles: Record<string, string> = {
    "/": "Kết nối để tìm lại",
    "/search": "Tìm đồ thất lạc",
    "/post": "Đăng tin nhặt được",
    "/requests": "Yêu cầu trao trả",
    "/messages": "Tin nhắn",
    "/posts": "Bài đăng của tôi",
    "/hubs": "Điểm tiếp nhận Findie Hub",
    "/intakes": "Theo dõi tiếp nhận",
    "/profile": "Hồ sơ cá nhân",
  };
  useEffect(() => {
    if (path !== "/signin")
      document.title = `${titles[path] ?? "Thông tin trao trả"} · Findie`;
  }, [path]);

  if (path === "/signin") return <SignIn />;
  function protect(content: () => ReactNode) {
    if (loading) return <Loading />;
    if (error)
      return (
        <ErrorNotice
          error={error}
          retry={() => setAttempt((value) => value + 1)}
        />
      );
    if (!user)
      return (
        <EmptyState title="Đăng nhập để tiếp tục" icon="document">
          <p>
            Dùng tài khoản Google để bảo vệ quyền riêng tư và kết nối trao trả
            đồ.
          </p>
          <a
            className="button"
            href={`/signin?returnUrl=${encodeURIComponent(path + window.location.search)}`}
          >
            Tiếp tục với Findie
            <Icon name="arrow" size={17} />
          </a>
        </EmptyState>
      );
    return content();
  }
  let content: ReactNode;
  if (path === "/") content = <Home signedIn={Boolean(user)} onImageSearch={(input) => {
    const query = new URLSearchParams({ mode: "image" });
    if (input.text) query.set("q", input.text);
    for (const [key, value] of Object.entries(input.filters))
      if (value) query.set(key, value);
    window.history.pushState(null, "", `/search?${query}`);
    setImageSearch(input);
    setLoading(true);
    setPath("/search");
  }} />;
  else if (path === "/search") content = protect(() => <Search initialRequest={imageSearch} />);
  else if (path === "/post") content = protect(() => <PostItem />);
  else if (path === "/posts") content = protect(() => <MyPosts />);
  else if (path === "/requests")
    content = protect(() => <Requests user={user!} />);
  else if (path === "/messages")
    content = protect(() => <Messages user={user!} />);
  else if (path === "/hubs") content = protect(() => <Points />);
  else if (path === "/profile") content = protect(() => <Profile user={user!} onUpdate={setUser} />);
  else if (path === "/intakes") content = protect(() => <Intakes user={user!} />);
  else if (intakeRoute) content = protect(() => <IntakeDetail id={intakeRoute[1]} user={user!} />);
  else if (itemRoute) {
    const [, id, view] = itemRoute;
    content = protect(() =>
      view === "claim" ? (
        <ClaimItem id={id} />
      ) : view === "review" ? (
        <ReviewImages id={id} />
      ) : view === "transfer" ? (
        <TransferItem id={id} />
      ) : view === "edit" ? (
        <PostItem id={id} />
      ) : view === "history" ? (
        <CustodyHistory id={id} />
      ) : view === "return" ? (
        <ReturnItem id={id} />
      ) : (
        <ItemDetail id={id} />
      ),
    );
  } else if (claimRoute)
    content = protect(() => <ClaimDetail id={claimRoute[1]} user={user!} />);
  else
    content = (
      <EmptyState title="Không tìm thấy trang">
        <p>Đường dẫn có thể đã thay đổi.</p>
        <a className="button" href="/">
          Về trang chủ
        </a>
      </EmptyState>
    );

  const active =
    path === "/search" || path === "/" || (itemRoute && !itemRoute[2])
      ? "search"
      : path === "/post" ||
          path === "/posts" ||
          itemRoute?.[2] === "edit" ||
          itemRoute?.[2] === "review" ||
          itemRoute?.[2] === "history" ||
          itemRoute?.[2] === "return" ||
          itemRoute?.[2] === "transfer"
        ? "posts"
        : path === "/requests" || claimRoute || itemRoute?.[2] === "claim"
          ? "requests"
          : path === "/messages"
            ? "messages"
            : "hubs";
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Chuyển đến nội dung
      </a>
      <header className="site-header">
        <div className="header-inner">
          <a href="/" className="brand" aria-label="Findie — Trang chủ">
            findie<span>.</span>
          </a>
          <nav className="main-nav" aria-label="Điều hướng chính">
            {[
              ["search", "/", "Tìm đồ"],
              ["posts", "/posts", "Bài đăng của tôi"],
              ["requests", "/requests", "Yêu cầu trao trả"],
              ["messages", "/messages", "Tin nhắn"],
            ].map(([key, href, label]) => (
              <a
                key={key}
                href={href}
                aria-current={active === key ? "page" : undefined}
              >
                {label}
              </a>
            ))}
          </nav>
          <div className="header-actions">
            <a
              className="hub-link"
              href="/hubs"
              aria-label="Findie Hub"
              aria-current={active === "hubs" ? "page" : undefined}
            >
              <Icon name="building" size={18} />
              <span>Findie Hub</span>
            </a>
            <a href="/post" className="button button-small" aria-label="Đăng tin">
              <Icon name="plus" size={17} />
              <span>Đăng tin</span>
            </a>
            {user ? (
              <details className="account-menu">
                <summary aria-label={`Tài khoản ${user.displayName}`}>
                  <span className="avatar">
                    {user.displayName.charAt(0).toLocaleUpperCase("vi")}
                  </span>
                </summary>
                <div>
                  <strong>{user.displayName}</strong>
                  <a href="/profile">Hồ sơ cá nhân</a>
                  <a href="/posts">Bài đăng của tôi</a>
                  <a href="/posts?scope=managed">Đồ đang quản lý</a>
                  <a href="/intakes">Theo dõi tiếp nhận</a>
                  <button
                    type="button"
                    disabled={action.busy}
                    onClick={() =>
                      void action.run(async () => {
                        await logout(AbortSignal.timeout(6000));
                        window.location.assign("/");
                      })
                    }
                  >
                    {action.busy ? "Đang đăng xuất…" : "Đăng xuất"}
                  </button>
                </div>
              </details>
            ) : (
              <a
                className="signin-link"
                href={`/signin?returnUrl=${encodeURIComponent(path + window.location.search)}`}
              >
                Đăng nhập
              </a>
            )}
          </div>
        </div>
      </header>
      <main
        id="main"
        className={`main-content${path === "/" ? " main-home" : ""}`}
      >
        {path !== "/" && (
          <Breadcrumb current={titles[path] ?? "Thông tin trao trả"} />
        )}
        <ErrorNotice error={action.error} />
        {content}
      </main>
      <footer className="site-footer">
        <div className="footer-inner">
          <div>
            <a href="/" className="brand">
              findie<span>.</span>
            </a>
            <p>Kết nối để tìm lại. Trao trả bằng sự tử tế.</p>
          </div>
          <div className="footer-links">
            <a href="/">Tìm đồ thất lạc</a>
            <a href="/post">Đăng tin nhặt được</a>
            <a href="/hubs">Mạng lưới Findie Hub</a>
          </div>
          <span className="footer-note">
            <Icon name="shield" size={16} />
            Vì một cộng đồng tin cậy
          </span>
        </div>
      </footer>
    </div>
  );
}
