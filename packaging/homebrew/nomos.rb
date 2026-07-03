# Fórmula Homebrew do NOMOS — TEMPLATE (preencher sha256/url na release final)
# Publicação: tap próprio (ex.: Voltolini-SPACE/homebrew-nomos) até entrar no core.
class Nomos < Formula
  include Language::Python::Virtualenv

  desc "Agente pessoal de IA 100% local — local por lei, fail-closed"
  homepage "https://github.com/Voltolini-SPACE/NOMOS"
  url "https://github.com/Voltolini-SPACE/NOMOS/releases/download/v1.0.0/nomos-1.0.0.tar.gz"
  sha256 "PREENCHER_NA_RELEASE"
  license "MIT"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "nomos", shell_output("#{bin}/nomos --version")
    # fail-closed: sem TTY, ação sensível é negada (rc=3)
    assert_equal 3, shell_output("#{bin}/nomos run 'echo x'; echo $?").strip.lines.last.to_i
  end
end
