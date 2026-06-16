"""
Implémentation d'une architecture Transformer from scratch en Python.
Basée sur le papier "Attention Is All You Need" (Vaswani et al., 2017).
"""

import logging
import math
import numpy as np


# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 1. FONCTIONS UTILITAIRES
# ─────────────────────────────────────────────

def softmax(x, axis=-1):
    """
    Applique la fonction softmax sur un axe donné.
    On soustrait le max pour la stabilité numérique (évite l'overflow).
    """
    x_shifted = x - np.max(x, axis=axis, keepdims=True)
    exp_x = np.exp(x_shifted)
    return exp_x / np.sum(exp_x, axis=axis, keepdims=True)


def relu(x):
    """Fonction d'activation ReLU : max(0, x)."""
    return np.maximum(0, x)


def layer_norm(x, gamma, beta, eps=1e-6):
    """
    Normalisation par couche (Layer Normalization).
    Normalise sur la dernière dimension (dimension du modèle),
    puis applique un scale (gamma) et un biais (beta) apprenables.
    """
    mean = np.mean(x, axis=-1, keepdims=True)
    var  = np.var(x, axis=-1, keepdims=True)
    x_norm = (x - mean) / np.sqrt(var + eps)
    return gamma * x_norm + beta


# ─────────────────────────────────────────────
# 2. ENCODAGE POSITIONNEL (Positional Encoding)
# ─────────────────────────────────────────────

def positional_encoding(seq_len, d_model):
    """
    Génère l'encodage positionnel sinusoïdal.

    Le Transformer n'a pas de récurrence, il ne "voit" pas l'ordre des tokens.
    On injecte donc l'information de position via des sinusoïdes :
      PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
      PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))

    Chaque dimension utilise une fréquence différente, ce qui permet
    au modèle d'apprendre des relations de positions relatives.
    """
    PE = np.zeros((seq_len, d_model))
    positions = np.arange(seq_len).reshape(-1, 1)          # (seq_len, 1)
    dims      = np.arange(0, d_model, 2)                   # indices pairs
    # Diviseur commun pour toutes les fréquences
    div_term  = np.power(10000.0, dims / d_model)          # (d_model/2,)

    PE[:, 0::2] = np.sin(positions / div_term)  # dimensions paires
    PE[:, 1::2] = np.cos(positions / div_term)  # dimensions impaires

    return PE  # (seq_len, d_model)


# ─────────────────────────────────────────────
# 3. ATTENTION SCALÉE PAR PRODUIT SCALAIRE
#    (Scaled Dot-Product Attention)
# ─────────────────────────────────────────────

def scaled_dot_product_attention(Q, K, V, mask=None):
    """
    Mécanisme d'attention fondamental du Transformer.

    Pour chaque position, on calcule à quel point elle doit "faire attention"
    aux autres positions, puis on agrège les valeurs en conséquence.

    Formule : Attention(Q, K, V) = softmax(QK^T / sqrt(d_k)) * V

    Arguments :
        Q : queries  (batch, heads, seq_q, d_k)
        K : keys     (batch, heads, seq_k, d_k)
        V : values   (batch, heads, seq_k, d_v)
        mask : masque optionnel pour bloquer certaines positions

    Retourne :
        output : (batch, heads, seq_q, d_v)
        weights : scores d'attention normalisés
    """
    d_k = Q.shape[-1]

    # Produit scalaire Q·K^T, divisé par sqrt(d_k) pour éviter
    # que les gradients ne s'évanouissent dans les grandes dimensions.
    scores = np.matmul(Q, K.swapaxes(-2, -1)) / math.sqrt(d_k)
    # scores : (batch, heads, seq_q, seq_k)

    if mask is not None:
        # On remplace les positions masquées par -∞ avant le softmax,
        # ce qui les ramènera à 0 après normalisation.
        scores = np.where(mask == 0, -1e9, scores)

    # Normalisation pour obtenir une distribution de probabilité
    weights = softmax(scores, axis=-1)  # (batch, heads, seq_q, seq_k)

    # Somme pondérée des valeurs
    output = np.matmul(weights, V)      # (batch, heads, seq_q, d_v)

    return output, weights


# ─────────────────────────────────────────────
# 4. ATTENTION MULTI-TÊTE (Multi-Head Attention)
# ─────────────────────────────────────────────

class MultiHeadAttention:
    """
    Attention multi-tête : on projette Q, K, V dans h sous-espaces différents,
    on applique l'attention dans chacun en parallèle, puis on concatène
    et re-projette le résultat.

    Cela permet au modèle d'apprendre différents types de relations
    (syntaxiques, sémantiques, etc.) simultanément.

    MultiHead(Q,K,V) = Concat(head_1,...,head_h) * W_O
    où head_i = Attention(Q*W_Q_i, K*W_K_i, V*W_V_i)
    """

    def __init__(self, d_model, num_heads, seed=0):
        assert d_model % num_heads == 0, "d_model doit être divisible par num_heads"

        self.d_model   = d_model
        self.num_heads = num_heads
        self.d_k       = d_model // num_heads  # dimension par tête

        rng = np.random.default_rng(seed)

        # Matrices de projection pour les queries, keys, values et la sortie.
        # Initialisées avec une distribution normale mise à l'échelle de Xavier.
        scale = math.sqrt(2.0 / (d_model + self.d_k))
        self.W_Q = rng.normal(0, scale, (d_model, d_model))  # (d_model, d_model)
        self.W_K = rng.normal(0, scale, (d_model, d_model))
        self.W_V = rng.normal(0, scale, (d_model, d_model))
        self.W_O = rng.normal(0, math.sqrt(2.0 / (d_model * 2)), (d_model, d_model))

    def split_heads(self, x, batch_size):
        """
        Réorganise le tenseur de (batch, seq, d_model)
        vers (batch, num_heads, seq, d_k) pour l'attention parallèle.
        """
        x = x.reshape(batch_size, -1, self.num_heads, self.d_k)
        return x.transpose(0, 2, 1, 3)  # (batch, heads, seq, d_k)

    def forward(self, Q_in, K_in, V_in, mask=None):
        """
        Passage avant de l'attention multi-tête.

        Q_in, K_in, V_in : (batch, seq, d_model)
        """
        batch_size = Q_in.shape[0]

        # 1. Projections linéaires vers l'espace d'attention
        Q = Q_in @ self.W_Q  # (batch, seq, d_model)
        K = K_in @ self.W_K
        V = V_in @ self.W_V

        # 2. Découpage en plusieurs têtes
        Q = self.split_heads(Q, batch_size)  # (batch, heads, seq, d_k)
        K = self.split_heads(K, batch_size)
        V = self.split_heads(V, batch_size)

        # 3. Attention scalée dans chaque tête
        attn_output, self.attn_weights = scaled_dot_product_attention(Q, K, V, mask)
        # attn_output : (batch, heads, seq, d_k)

        # 4. Concaténation des têtes : (batch, seq, d_model)
        attn_output = attn_output.transpose(0, 2, 1, 3)
        attn_output = attn_output.reshape(batch_size, -1, self.d_model)

        # 5. Projection linéaire finale
        output = attn_output @ self.W_O  # (batch, seq, d_model)

        return output


# ─────────────────────────────────────────────
# 5. RÉSEAU FEED-FORWARD PAR POSITION
#    (Position-wise Feed-Forward Network)
# ─────────────────────────────────────────────

class FeedForward:
    """
    Réseau feed-forward appliqué indépendamment à chaque position.
    Composé de deux transformations linéaires avec une activation ReLU :

        FFN(x) = ReLU(x * W1 + b1) * W2 + b2

    La dimension intermédiaire d_ff est généralement 4×d_model.
    Ce réseau apporte la capacité non-linéaire du Transformer.
    """

    def __init__(self, d_model, d_ff, seed=1):
        rng = np.random.default_rng(seed)
        scale1 = math.sqrt(2.0 / d_model)
        scale2 = math.sqrt(2.0 / d_ff)

        self.W1 = rng.normal(0, scale1, (d_model, d_ff))
        self.b1 = np.zeros(d_ff)
        self.W2 = rng.normal(0, scale2, (d_ff, d_model))
        self.b2 = np.zeros(d_model)

    def forward(self, x):
        """x : (batch, seq, d_model)"""
        # Première couche linéaire + activation ReLU
        hidden = relu(x @ self.W1 + self.b1)  # (batch, seq, d_ff)
        # Deuxième couche linéaire
        return hidden @ self.W2 + self.b2      # (batch, seq, d_model)


# ─────────────────────────────────────────────
# 6. BLOC ENCODEUR (Encoder Layer)
# ─────────────────────────────────────────────

class EncoderLayer:
    """
    Un bloc encodeur contient :
      1. Self-attention multi-tête + connexion résiduelle + LayerNorm
      2. Feed-forward + connexion résiduelle + LayerNorm

    Les connexions résiduelles (Add & Norm) permettent le flux du gradient
    et évitent la dégradation du signal dans les réseaux profonds.
    """

    def __init__(self, d_model, num_heads, d_ff, seed=0):
        self.self_attn  = MultiHeadAttention(d_model, num_heads, seed=seed)
        self.ff         = FeedForward(d_model, d_ff, seed=seed + 10)

        # Paramètres apprenables de la normalisation (gamma=1, beta=0 initialement)
        self.gamma1 = np.ones(d_model)
        self.beta1  = np.zeros(d_model)
        self.gamma2 = np.ones(d_model)
        self.beta2  = np.zeros(d_model)

    def forward(self, x, mask=None):
        """
        x    : (batch, seq, d_model)
        mask : masque de padding (positions à ignorer)
        """
        # --- Sous-couche 1 : Self-Attention ---
        # L'encodeur voit toute la séquence source (Q=K=V=x)
        attn_out = self.self_attn.forward(x, x, x, mask)
        # Connexion résiduelle + normalisation
        x = layer_norm(x + attn_out, self.gamma1, self.beta1)

        # --- Sous-couche 2 : Feed-Forward ---
        ff_out = self.ff.forward(x)
        # Connexion résiduelle + normalisation
        x = layer_norm(x + ff_out, self.gamma2, self.beta2)

        return x  # (batch, seq, d_model)


# ─────────────────────────────────────────────
# 7. BLOC DÉCODEUR (Decoder Layer)
# ─────────────────────────────────────────────

class DecoderLayer:
    """
    Un bloc décodeur contient trois sous-couches :
      1. Self-attention masquée (ne voit que les tokens passés)
      2. Cross-attention sur la sortie de l'encodeur (source-cible)
      3. Feed-forward

    Le masque causal (look-ahead mask) garantit que le décodeur
    est auto-régressif : il ne peut pas "tricher" en regardant le futur.
    """

    def __init__(self, d_model, num_heads, d_ff, seed=0):
        self.self_attn  = MultiHeadAttention(d_model, num_heads, seed=seed)
        self.cross_attn = MultiHeadAttention(d_model, num_heads, seed=seed + 20)
        self.ff         = FeedForward(d_model, d_ff, seed=seed + 30)

        self.gamma1 = np.ones(d_model)
        self.beta1  = np.zeros(d_model)
        self.gamma2 = np.ones(d_model)
        self.beta2  = np.zeros(d_model)
        self.gamma3 = np.ones(d_model)
        self.beta3  = np.zeros(d_model)

    def forward(self, x, encoder_out, src_mask=None, tgt_mask=None):
        """
        x           : tokens cibles     (batch, tgt_seq, d_model)
        encoder_out : sortie encodeur   (batch, src_seq, d_model)
        src_mask    : masque source (padding)
        tgt_mask    : masque causal (look-ahead)
        """
        # --- Sous-couche 1 : Self-Attention masquée ---
        # Q=K=V=x, avec masque causal pour l'auto-régression
        attn1 = self.self_attn.forward(x, x, x, tgt_mask)
        x = layer_norm(x + attn1, self.gamma1, self.beta1)

        # --- Sous-couche 2 : Cross-Attention (encodeur → décodeur) ---
        # Q vient du décodeur, K et V viennent de l'encodeur
        # Cela permet au décodeur de "consulter" la séquence source
        attn2 = self.cross_attn.forward(x, encoder_out, encoder_out, src_mask)
        x = layer_norm(x + attn2, self.gamma2, self.beta2)

        # --- Sous-couche 3 : Feed-Forward ---
        ff_out = self.ff.forward(x)
        x = layer_norm(x + ff_out, self.gamma3, self.beta3)

        return x  # (batch, tgt_seq, d_model)


# ─────────────────────────────────────────────
# 8. ENCODEUR COMPLET
# ─────────────────────────────────────────────

class Encoder:
    """
    Empilement de N blocs encodeurs.
    Transforme la séquence source en représentations contextuelles riches.
    """

    def __init__(self, vocab_size, d_model, num_heads, d_ff, num_layers, max_seq_len=512, seed=0):
        # Table d'embeddings : chaque token → vecteur dense de dimension d_model
        rng = np.random.default_rng(seed)
        self.embedding = rng.normal(0, math.sqrt(1.0 / d_model), (vocab_size, d_model))

        # Encodage positionnel pré-calculé (non appris ici)
        self.pos_encoding = positional_encoding(max_seq_len, d_model)

        self.d_model = d_model
        self.layers  = [EncoderLayer(d_model, num_heads, d_ff, seed=seed + i) for i in range(num_layers)]

    def forward(self, src_tokens, src_mask=None):
        """
        src_tokens : indices entiers (batch, src_seq)
        """
        seq_len = src_tokens.shape[1]

        # 1. Embedding des tokens
        x = self.embedding[src_tokens]           # (batch, seq, d_model)

        # 2. Ajout de l'encodage positionnel
        # On met à l'échelle l'embedding par sqrt(d_model) (comme dans le papier)
        x = x * math.sqrt(self.d_model) + self.pos_encoding[:seq_len]

        # 3. Passage dans chaque bloc encodeur
        for layer in self.layers:
            x = layer.forward(x, src_mask)

        return x  # (batch, src_seq, d_model)


# ─────────────────────────────────────────────
# 9. DÉCODEUR COMPLET
# ─────────────────────────────────────────────

class Decoder:
    """
    Empilement de N blocs décodeurs.
    Génère la séquence cible token par token à partir
    des représentations de l'encodeur.
    """

    def __init__(self, vocab_size, d_model, num_heads, d_ff, num_layers, max_seq_len=512, seed=42):
        rng = np.random.default_rng(seed)
        self.embedding    = rng.normal(0, math.sqrt(1.0 / d_model), (vocab_size, d_model))
        self.pos_encoding = positional_encoding(max_seq_len, d_model)

        self.d_model = d_model
        self.layers  = [DecoderLayer(d_model, num_heads, d_ff, seed=seed + i) for i in range(num_layers)]

    def forward(self, tgt_tokens, encoder_out, src_mask=None, tgt_mask=None):
        """
        tgt_tokens  : indices entiers (batch, tgt_seq)
        encoder_out : sortie encodeur (batch, src_seq, d_model)
        """
        seq_len = tgt_tokens.shape[1]

        x = self.embedding[tgt_tokens] * math.sqrt(self.d_model) + self.pos_encoding[:seq_len]

        for layer in self.layers:
            x = layer.forward(x, encoder_out, src_mask, tgt_mask)

        return x  # (batch, tgt_seq, d_model)


# ─────────────────────────────────────────────
# 10. TRANSFORMER COMPLET
# ─────────────────────────────────────────────

class Transformer:
    """
    Architecture Transformer complète (encodeur-décodeur).

    Hyperparamètres typiques du papier original :
        d_model    = 512
        num_heads  = 8
        d_ff       = 2048
        num_layers = 6
    """

    def __init__(self, src_vocab_size, tgt_vocab_size, d_model=512, num_heads=8,
                 d_ff=2048, num_layers=6, max_seq_len=512):

        self.encoder = Encoder(src_vocab_size, d_model, num_heads, d_ff, num_layers, max_seq_len, seed=0)
        self.decoder = Decoder(tgt_vocab_size, d_model, num_heads, d_ff, num_layers, max_seq_len, seed=42)

        # Couche de projection finale : d_model → tgt_vocab_size
        # Transforme les représentations en logits sur le vocabulaire cible
        rng = np.random.default_rng(99)
        self.W_out = rng.normal(0, math.sqrt(1.0 / d_model), (d_model, tgt_vocab_size))

    @staticmethod
    def make_padding_mask(seq, pad_idx=0):
        """
        Crée un masque pour ignorer les tokens de padding.
        Shape de sortie : (batch, 1, 1, seq_len) pour le broadcasting.
        """
        return (seq != pad_idx).astype(np.float32)[:, np.newaxis, np.newaxis, :]

    @staticmethod
    def make_causal_mask(seq_len):
        """
        Crée un masque causal (triangulaire inférieur) pour le décodeur.
        La position i ne peut voir que les positions 0..i.
        Shape : (1, 1, seq_len, seq_len)
        """
        mask = np.tril(np.ones((seq_len, seq_len), dtype=np.float32))
        return mask[np.newaxis, np.newaxis, :, :]  # (1, 1, seq, seq)

    def forward(self, src_tokens, tgt_tokens, src_pad_idx=0, tgt_pad_idx=0):
        """
        src_tokens : séquence source  (batch, src_seq)
        tgt_tokens : séquence cible   (batch, tgt_seq)

        Retourne les logits (batch, tgt_seq, tgt_vocab_size).
        """
        tgt_seq_len = tgt_tokens.shape[1]

        # Construction des masques
        src_mask = self.make_padding_mask(src_tokens, src_pad_idx)
        # Pour le décodeur : combiner masque de padding ET masque causal
        tgt_pad_mask  = self.make_padding_mask(tgt_tokens, tgt_pad_idx)
        tgt_look_mask = self.make_causal_mask(tgt_seq_len)
        tgt_mask      = tgt_pad_mask * tgt_look_mask  # (batch, 1, tgt_seq, tgt_seq)

        # Encodage de la séquence source
        encoder_out = self.encoder.forward(src_tokens, src_mask)

        # Décodage de la séquence cible
        decoder_out = self.decoder.forward(tgt_tokens, encoder_out, src_mask, tgt_mask)

        # Projection vers le vocabulaire cible
        logits = decoder_out @ self.W_out  # (batch, tgt_seq, tgt_vocab_size)

        return logits

    def predict(self, logits):
        """Retourne l'indice du token le plus probable à chaque position."""
        return np.argmax(logits, axis=-1)


# ─────────────────────────────────────────────
# 11. DÉMONSTRATION
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  Transformer from scratch — démonstration")
    logger.info("=" * 60)

    # Hyperparamètres réduits pour la démo
    SRC_VOCAB = 100
    TGT_VOCAB = 80
    D_MODEL   = 64
    NUM_HEADS = 4
    D_FF      = 128
    N_LAYERS  = 2
    BATCH     = 2
    SRC_LEN   = 6
    TGT_LEN   = 5

    # Instanciation du modèle
    model = Transformer(
        src_vocab_size=SRC_VOCAB,
        tgt_vocab_size=TGT_VOCAB,
        d_model=D_MODEL,
        num_heads=NUM_HEADS,
        d_ff=D_FF,
        num_layers=N_LAYERS,
    )

    # Données factices (indices de tokens, 0 = padding)
    rng = np.random.default_rng(7)
    src = rng.integers(1, SRC_VOCAB, size=(BATCH, SRC_LEN))
    tgt = rng.integers(1, TGT_VOCAB, size=(BATCH, TGT_LEN))
    # Simuler du padding à la fin
    src[:, -1] = 0
    tgt[:, -1] = 0

    logger.info("Séquence source  : shape %s", src.shape)
    logger.info("Séquence cible   : shape %s", tgt.shape)

    # Passage avant
    logits = model.forward(src, tgt)

    logger.info("Logits           : shape %s  (batch, tgt_seq, tgt_vocab)", logits.shape)

    predictions = model.predict(logits)
    logger.info("Prédictions      : shape %s", predictions.shape)
    logger.info("Tokens prédits   :\n%s", predictions)

    # Vérification de l'encodage positionnel
    PE = positional_encoding(10, D_MODEL)
    logger.info("Encodage positionnel (10 pos, d=%d) : shape %s", D_MODEL, PE.shape)
    logger.info("Valeurs PE[0,:4] = %s", PE[0, :4].round(4))
    logger.info("Valeurs PE[1,:4] = %s", PE[1, :4].round(4))

    # Vérification des poids d'attention (dernière couche de l'encodeur)
    enc_layer   = model.encoder.layers[-1]
    attn_w      = enc_layer.self_attn.attn_weights   # (batch, heads, seq, seq)
    logger.info("Poids d'attention (dernière couche encodeur) : shape %s", attn_w.shape)
    logger.info("Somme sur l'axe seq_k (doit ≈ 1) : %s", attn_w[0, 0].sum(axis=-1).round(4))

    logger.info("Done.")
