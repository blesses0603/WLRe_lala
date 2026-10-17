public class VaultBuilder implements java.security.spec.AlgorithmParameterSpec {
    public String mode;
    public String padding;
    public int bits;
    public VaultBuilder(String alias, int purpose) {}
    public VaultBuilder setKeySize(int bits) { this.bits = bits; return this; }
    public VaultBuilder setBlockModes(String... modes) {
        if (modes.length != 1) throw new IllegalArgumentException();
        mode = modes[0]; return this;
    }
    public VaultBuilder setEncryptionPaddings(String... paddings) {
        if (paddings.length != 1) throw new IllegalArgumentException();
        padding = paddings[0]; return this;
    }
    public VaultBuilder build() { return this; }
}
